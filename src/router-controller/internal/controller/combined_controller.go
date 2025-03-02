/*
Copyright 2025.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package controller

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	"sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	productionstackv1alpha1 "github.com/vllm-project/production-stack/router-controller/api/v1alpha1"
)

// CombinedDynamicConfig represents the dynamic configuration for the vllm_router
// combining Backend and Route information
type CombinedDynamicConfig struct {
	ServiceDiscovery string        `json:"service_discovery"`
	RoutingLogic     string        `json:"routing_logic"`
	StaticBackends   string        `json:"static_backends"`
	StaticModels     string        `json:"static_models"`
	Routes           []RouteConfig `json:"routes,omitempty"`
}

// RouteConfig represents a single route configuration
type RouteConfig struct {
	Path      string `json:"path"`
	APISchema string `json:"api_schema"`
	Weight    int32  `json:"weight"`
	Backend   string `json:"backend"`
}

// CombinedReconciler reconciles Backend and Route objects together
type CombinedReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

//+kubebuilder:rbac:groups=production-stack.vllm.ai,resources=backends,verbs=get;list;watch
//+kubebuilder:rbac:groups=production-stack.vllm.ai,resources=routes,verbs=get;list;watch
//+kubebuilder:rbac:groups=core,resources=configmaps,verbs=get;list;watch;create;update;patch;delete

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
func (r *CombinedReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)
	logger.Info("Reconciling combined resources")

	// List all available backends
	backendList := &productionstackv1alpha1.BackendList{}
	if err := r.List(ctx, backendList); err != nil {
		logger.Error(err, "Failed to list backends")
		return ctrl.Result{}, err
	}

	// Filter for available backends
	availableBackends := make(map[types.NamespacedName]*productionstackv1alpha1.Backend)
	for i := range backendList.Items {
		backend := &backendList.Items[i]
		if backend.Status.IsAvailable {
			key := types.NamespacedName{
				Name:      backend.Name,
				Namespace: backend.Namespace,
			}
			availableBackends[key] = backend
		}
	}

	// Check for StaticRoute CRD
	staticRouteList := &productionstackv1alpha1.StaticRouteList{}
	if err := r.List(ctx, staticRouteList); err != nil {
		logger.Error(err, "Failed to list static routes")
		return ctrl.Result{}, err
	}

	// If StaticRoute exists, use it to create the configmap
	if len(staticRouteList.Items) > 0 {
		staticRoute := &staticRouteList.Items[0] // Use the first StaticRoute found
		return r.reconcileStaticRoute(ctx, staticRoute)
	}

	// If no StaticRoute exists, check for Routes
	routeList := &productionstackv1alpha1.RouteList{}
	if err := r.List(ctx, routeList); err != nil {
		logger.Error(err, "Failed to list routes")
		return ctrl.Result{}, err
	}

	// If no Routes exist, don't create a configmap
	if len(routeList.Items) == 0 {
		logger.Info("No StaticRoute or Routes found, no configmap needed")
		return ctrl.Result{RequeueAfter: 30 * time.Second}, nil
	}

	// Build the combined configuration from Routes
	routeConfigs := []RouteConfig{}
	backendEndpoints := []string{}
	backendModels := []string{}

	for i := range routeList.Items {
		route := &routeList.Items[i]

		// Check if the referenced backend exists and is available
		backendKey := types.NamespacedName{
			Name:      route.Spec.BackendRef.Name,
			Namespace: route.Spec.BackendRef.Namespace,
		}
		if backendKey.Namespace == "" {
			backendKey.Namespace = route.Namespace
		}

		backend, exists := availableBackends[backendKey]
		if !exists {
			logger.Info("Referenced backend not available", "route", route.Name, "backend", backendKey)
			continue
		}

		// Add route configuration
		routeConfig := RouteConfig{
			Path:      route.Spec.Path,
			APISchema: route.Spec.APISchema,
			Weight:    route.Spec.Weight,
			Backend:   r.getEndpointString(backend),
		}
		routeConfigs = append(routeConfigs, routeConfig)

		// Add backend endpoint and models if not already added
		backendEndpoint := r.getEndpointString(backend)
		if !contains(backendEndpoints, backendEndpoint) {
			backendEndpoints = append(backendEndpoints, backendEndpoint)
		}
		if !contains(backendModels, backend.Spec.Models) {
			backendModels = append(backendModels, backend.Spec.Models)
		}
	}

	// If no valid routes found, don't create a configmap
	if len(routeConfigs) == 0 {
		logger.Info("No valid routes found, no configmap needed")
		return ctrl.Result{RequeueAfter: 30 * time.Second}, nil
	}

	// Create the combined dynamic configuration
	dynamicConfig := CombinedDynamicConfig{
		ServiceDiscovery: "static",
		RoutingLogic:     "roundrobin",
		StaticBackends:   joinStrings(backendEndpoints, ","),
		StaticModels:     joinStrings(backendModels, ","),
		Routes:           routeConfigs,
	}

	// Create or update the ConfigMap
	if err := r.reconcileConfigMap(ctx, dynamicConfig); err != nil {
		logger.Error(err, "Failed to reconcile ConfigMap")
		return ctrl.Result{}, err
	}

	return ctrl.Result{RequeueAfter: 30 * time.Second}, nil
}

// reconcileStaticRoute creates a configmap from a StaticRoute CRD
func (r *CombinedReconciler) reconcileStaticRoute(ctx context.Context, staticRoute *productionstackv1alpha1.StaticRoute) (ctrl.Result, error) {
	logger := log.FromContext(ctx)

	// Create dynamic config from StaticRoute
	dynamicConfig := CombinedDynamicConfig{
		ServiceDiscovery: "static",
		RoutingLogic:     staticRoute.Spec.RoutingLogic,
		StaticBackends:   staticRoute.Spec.StaticBackends,
		StaticModels:     staticRoute.Spec.StaticModels,
	}

	// Create or update the ConfigMap
	if err := r.reconcileConfigMap(ctx, dynamicConfig); err != nil {
		logger.Error(err, "Failed to reconcile ConfigMap from StaticRoute")
		return ctrl.Result{}, err
	}

	return ctrl.Result{RequeueAfter: 30 * time.Second}, nil
}

// contains checks if a string is present in a slice
func contains(slice []string, str string) bool {
	for _, s := range slice {
		if s == str {
			return true
		}
	}
	return false
}

// joinStrings joins a slice of strings with the specified separator
func joinStrings(strings []string, separator string) string {
	result := ""
	for i, s := range strings {
		if i > 0 {
			result += separator
		}
		result += s
	}
	return result
}

// reconcileConfigMap creates or updates the ConfigMap with the combined dynamic configuration
func (r *CombinedReconciler) reconcileConfigMap(ctx context.Context, dynamicConfig CombinedDynamicConfig) error {
	logger := log.FromContext(ctx)

	// Convert the dynamic configuration to JSON
	dynamicConfigJSON, err := json.Marshal(dynamicConfig)
	if err != nil {
		return fmt.Errorf("failed to marshal dynamic configuration: %w", err)
	}

	// Create or update the ConfigMap
	configMap := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "vllm-router-config", // Use a fixed name for the combined config
			Namespace: "default",            // Use the default namespace
		},
	}

	// Create or update the ConfigMap
	_, err = controllerutil.CreateOrUpdate(ctx, r.Client, configMap, func() error {
		if configMap.Data == nil {
			configMap.Data = make(map[string]string)
		}
		configMap.Data["dynamic_config.json"] = string(dynamicConfigJSON)
		return nil
	})
	if err != nil {
		return fmt.Errorf("failed to create or update ConfigMap: %w", err)
	}

	logger.Info("Combined ConfigMap reconciled successfully", "namespace", configMap.Namespace, "name", configMap.Name)
	return nil
}

// SetupWithManager sets up the controller with the Manager.
func (r *CombinedReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		Named("combined-controller").
		For(&productionstackv1alpha1.StaticRoute{}).
		Watches(
			&productionstackv1alpha1.Route{},
			handler.EnqueueRequestsFromMapFunc(func(ctx context.Context, obj client.Object) []reconcile.Request {
				return []reconcile.Request{
					{NamespacedName: types.NamespacedName{
						Name:      "trigger-reconcile", // Dummy name to trigger reconcile
						Namespace: obj.GetNamespace(),
					}},
				}
			}),
		).
		Watches(
			&productionstackv1alpha1.Backend{},
			handler.EnqueueRequestsFromMapFunc(func(ctx context.Context, obj client.Object) []reconcile.Request {
				return []reconcile.Request{
					{NamespacedName: types.NamespacedName{
						Name:      "trigger-reconcile", // Dummy name to trigger reconcile
						Namespace: obj.GetNamespace(),
					}},
				}
			}),
		).
		Owns(&corev1.ConfigMap{}).
		Complete(r)
}

// getEndpointString converts the BackendEndpoint to a string representation
func (r *CombinedReconciler) getEndpointString(backend *productionstackv1alpha1.Backend) string {
	// Handle different endpoint types
	if backend.Spec.Endpoint.URL != "" {
		return backend.Spec.Endpoint.URL
	}

	if backend.Spec.Endpoint.Service != nil {
		service := backend.Spec.Endpoint.Service
		namespace := service.ObjectReference.Namespace
		if namespace == "" {
			namespace = backend.Namespace
		}

		// Format: http://service-name.namespace.svc.cluster.local:port
		return fmt.Sprintf("http://%s.%s.svc.cluster.local:%d",
			service.ObjectReference.Name,
			namespace,
			service.Port)
	}

	if backend.Spec.Endpoint.FQDN != nil {
		fqdn := backend.Spec.Endpoint.FQDN
		return fmt.Sprintf("http://%s:%d", fqdn.Hostname, fqdn.Port)
	}

	if backend.Spec.Endpoint.IP != nil {
		ip := backend.Spec.Endpoint.IP
		return fmt.Sprintf("http://%s:%d", ip.Address, ip.Port)
	}

	if backend.Spec.Endpoint.Unix != nil {
		unix := backend.Spec.Endpoint.Unix
		return fmt.Sprintf("unix://%s", unix.Path)
	}

	// Fallback to deprecated ServiceRef if present
	if backend.Spec.ServiceRef != nil {
		namespace := backend.Spec.ServiceRef.Namespace
		if namespace == "" {
			namespace = backend.Namespace
		}

		// Format: http://service-name.namespace.svc.cluster.local:8000 (default port)
		return fmt.Sprintf("http://%s.%s.svc.cluster.local:8000",
			backend.Spec.ServiceRef.Name,
			namespace)
	}

	// Should not reach here if validation is working correctly
	return ""
}
