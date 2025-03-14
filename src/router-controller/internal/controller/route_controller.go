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
	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
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

// RouteDynamicConfig represents the dynamic configuration for the vllm_router
// when using Route CRD
type RouteDynamicConfig struct {
	ServiceDiscovery string `json:"service_discovery"`
	RoutingLogic     string `json:"routing_logic"`
	StaticBackends   string `json:"static_backends"`
	StaticModels     string `json:"static_models"`
	Path             string `json:"path,omitempty"`
	APISchema        string `json:"api_schema,omitempty"`
	Weight           int32  `json:"weight,omitempty"`
	APIKey           string `json:"api_key,omitempty"`
}

// RouteReconciler reconciles a Route object
type RouteReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

//+kubebuilder:rbac:groups=production-stack.vllm.ai,resources=routes,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=production-stack.vllm.ai,resources=routes/status,verbs=get;update;patch
//+kubebuilder:rbac:groups=production-stack.vllm.ai,resources=routes/finalizers,verbs=update
//+kubebuilder:rbac:groups=production-stack.vllm.ai,resources=backends,verbs=get;list;watch
//+kubebuilder:rbac:groups=core,resources=configmaps,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=core,resources=secrets,verbs=get;list;watch

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
func (r *RouteReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)
	logger.Info("Reconciling Route", "name", req.NamespacedName)

	// Fetch the Route instance
	route := &productionstackv1alpha1.Route{}
	err := r.Get(ctx, req.NamespacedName, route)
	if err != nil {
		if errors.IsNotFound(err) {
			// Request object not found, could have been deleted after reconcile request.
			// Return and don't requeue
			logger.Info("Route resource not found. Ignoring since object must be deleted")
			return ctrl.Result{}, nil
		}
		// Error reading the object - requeue the request.
		logger.Error(err, "Failed to get Route")
		return ctrl.Result{}, err
	}

	// Initialize status if it's not set
	if route.Status.Conditions == nil {
		route.Status.Conditions = []metav1.Condition{}
	}

	// Check if the referenced backend exists
	backend := &productionstackv1alpha1.Backend{}
	backendNamespacedName := types.NamespacedName{
		Name:      route.Spec.BackendRef.Name,
		Namespace: route.Spec.BackendRef.Namespace,
	}
	if backendNamespacedName.Namespace == "" {
		backendNamespacedName.Namespace = req.Namespace
	}

	err = r.Get(ctx, backendNamespacedName, backend)
	if err != nil {
		if errors.IsNotFound(err) {
			// Backend not found, update status and requeue
			logger.Info("Referenced Backend not found", "backend", backendNamespacedName)
			meta.SetStatusCondition(&route.Status.Conditions, metav1.Condition{
				Type:               "BackendAvailable",
				Status:             metav1.ConditionFalse,
				Reason:             "BackendNotFound",
				Message:            fmt.Sprintf("Backend %s not found", backendNamespacedName),
				LastTransitionTime: metav1.Now(),
			})
			route.Status.IsActive = false
		} else {
			// Error reading the backend - requeue the request.
			logger.Error(err, "Failed to get Backend")
			return ctrl.Result{}, err
		}
	} else {
		// Backend found, check if it's available
		if backend.Status.IsAvailable {
			meta.SetStatusCondition(&route.Status.Conditions, metav1.Condition{
				Type:               "BackendAvailable",
				Status:             metav1.ConditionTrue,
				Reason:             "BackendAvailable",
				Message:            "Backend is available",
				LastTransitionTime: metav1.Now(),
			})
		} else {
			meta.SetStatusCondition(&route.Status.Conditions, metav1.Condition{
				Type:               "BackendAvailable",
				Status:             metav1.ConditionFalse,
				Reason:             "BackendUnavailable",
				Message:            "Backend is not available",
				LastTransitionTime: metav1.Now(),
			})
			route.Status.IsActive = false
		}
	}

	// Check if the route is properly configured
	isConfigured := r.validateRouteConfiguration(route)
	if isConfigured {
		meta.SetStatusCondition(&route.Status.Conditions, metav1.Condition{
			Type:               "Configured",
			Status:             metav1.ConditionTrue,
			Reason:             "ValidConfiguration",
			Message:            "Route is properly configured",
			LastTransitionTime: metav1.Now(),
		})
	} else {
		meta.SetStatusCondition(&route.Status.Conditions, metav1.Condition{
			Type:               "Configured",
			Status:             metav1.ConditionFalse,
			Reason:             "InvalidConfiguration",
			Message:            "Route configuration is invalid",
			LastTransitionTime: metav1.Now(),
		})
		route.Status.IsActive = false
	}

	// If backend is available and route is properly configured, mark the route as active
	backendAvailableCondition := meta.FindStatusCondition(route.Status.Conditions, "BackendAvailable")
	configuredCondition := meta.FindStatusCondition(route.Status.Conditions, "Configured")

	if backendAvailableCondition != nil && configuredCondition != nil &&
		backendAvailableCondition.Status == metav1.ConditionTrue &&
		configuredCondition.Status == metav1.ConditionTrue {
		route.Status.IsActive = true
	}

	// Create or update the ConfigMap with the dynamic configuration if backend is available
	if backend != nil && backend.Status.IsAvailable {
		configMap, err := r.reconcileConfigMap(ctx, route, backend)
		if err != nil {
			logger.Error(err, "Failed to reconcile ConfigMap")
			return ctrl.Result{}, err
		}

		// Update the status with the ConfigMap reference
		meta.SetStatusCondition(&route.Status.Conditions, metav1.Condition{
			Type:               "ConfigMapCreated",
			Status:             metav1.ConditionTrue,
			Reason:             "ConfigMapCreated",
			Message:            fmt.Sprintf("ConfigMap %s created", configMap.Name),
			LastTransitionTime: metav1.Now(),
		})
	}

	// Update the status fields
	route.Status.LastConfiguredTime = &metav1.Time{Time: time.Now()}

	// Update the Route status
	if err := r.Status().Update(ctx, route); err != nil {
		logger.Error(err, "Failed to update Route status")
		return ctrl.Result{}, err
	}

	// Requeue after a period to check status again
	return ctrl.Result{RequeueAfter: 30 * time.Second}, nil
}

// reconcileConfigMap creates or updates the ConfigMap with the dynamic configuration
func (r *RouteReconciler) reconcileConfigMap(ctx context.Context, route *productionstackv1alpha1.Route, backend *productionstackv1alpha1.Backend) (*corev1.ConfigMap, error) {
	logger := log.FromContext(ctx)

	// Create a dynamic configuration for the route
	dynamicConfig := &RouteDynamicConfig{
		ServiceDiscovery: "static",     // Default to static service discovery
		RoutingLogic:     "roundrobin", // Default to roundrobin
		StaticBackends:   r.getEndpointString(backend),
		StaticModels:     backend.Spec.Models,
		Path:             route.Spec.Path,
		APISchema:        route.Spec.APISchema,
		Weight:           route.Spec.Weight,
	}

	// API key should now come from the backend, not the route
	if backend.Spec.SecretRef != nil {
		// The API key is handled by the backend controller
		// We just need to check if it's available
		condition := meta.FindStatusCondition(backend.Status.Conditions, "SecretAvailable")
		if condition != nil && condition.Status == metav1.ConditionTrue {
			// The backend has the API key available
			// We don't need to set it here as it's handled by the backend controller
			meta.SetStatusCondition(&route.Status.Conditions, metav1.Condition{
				Type:               "SecretAvailable",
				Status:             metav1.ConditionTrue,
				Reason:             "SecretAvailable",
				Message:            "Secret is available via backend",
				LastTransitionTime: metav1.Now(),
			})
		} else {
			// The backend doesn't have the API key available
			meta.SetStatusCondition(&route.Status.Conditions, metav1.Condition{
				Type:               "SecretAvailable",
				Status:             metav1.ConditionFalse,
				Reason:             "BackendSecretNotAvailable",
				Message:            "Secret is not available via backend",
				LastTransitionTime: metav1.Now(),
			})
		}
	}

	// Convert the dynamic configuration to JSON
	dynamicConfigJSON, err := json.Marshal(dynamicConfig)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal dynamic configuration: %w", err)
	}

	// Create or update the ConfigMap
	configMap := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      route.Spec.ConfigMapRef.Name,
			Namespace: route.Namespace,
		},
	}

	// Set the owner reference
	if err := controllerutil.SetControllerReference(route, configMap, r.Scheme); err != nil {
		return nil, fmt.Errorf("failed to set owner reference: %w", err)
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
		return nil, fmt.Errorf("failed to create or update ConfigMap: %w", err)
	}

	logger.Info("ConfigMap reconciled successfully", "namespace", configMap.Namespace, "name", configMap.Name)
	return configMap, nil
}

// getEndpointString converts the BackendEndpoint to a string representation
func (r *RouteReconciler) getEndpointString(backend *productionstackv1alpha1.Backend) string {
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

// validateRouteConfiguration validates the route configuration
func (r *RouteReconciler) validateRouteConfiguration(route *productionstackv1alpha1.Route) bool {
	// Check if path is set
	if route.Spec.Path == "" {
		return false
	}

	// Check if API schema is valid
	validSchemas := map[string]bool{
		"openai":    true,
		"anthropic": true,
		"vllm":      true,
	}
	if !validSchemas[route.Spec.APISchema] {
		return false
	}

	// We no longer need to check for secretRef in the route
	// as it's now handled by the backend

	// Check if semantic caching configuration is valid when enabled
	if route.Spec.SemanticCachingEnabled && route.Spec.SemanticCachingConfig != nil {
		// Validate TTL
		if route.Spec.SemanticCachingConfig.TTL <= 0 {
			return false
		}

		// Validate similarity threshold
		if route.Spec.SemanticCachingConfig.SimilarityThreshold < 0 ||
			route.Spec.SemanticCachingConfig.SimilarityThreshold > 100 {
			return false
		}

		// Validate max cache size
		if route.Spec.SemanticCachingConfig.MaxCacheSize <= 0 {
			return false
		}
	}

	// All checks passed
	return true
}

// SetupWithManager sets up the controller with the Manager.
func (r *RouteReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&productionstackv1alpha1.Route{}).
		Owns(&corev1.ConfigMap{}).
		Watches(
			&productionstackv1alpha1.Backend{},
			handler.EnqueueRequestsFromMapFunc(func(ctx context.Context, obj client.Object) []reconcile.Request {
				// Get all routes that reference this backend
				routeList := &productionstackv1alpha1.RouteList{}
				if err := r.List(ctx, routeList); err != nil {
					return nil
				}

				var requests []reconcile.Request
				backend := obj.(*productionstackv1alpha1.Backend)
				for _, route := range routeList.Items {
					if route.Spec.BackendRef.Name == backend.Name &&
						(route.Spec.BackendRef.Namespace == backend.Namespace ||
							(route.Spec.BackendRef.Namespace == "" && route.Namespace == backend.Namespace)) {
						requests = append(requests, reconcile.Request{
							NamespacedName: types.NamespacedName{
								Name:      route.Name,
								Namespace: route.Namespace,
							},
						})
					}
				}
				return requests
			}),
		).
		Complete(r)
}
