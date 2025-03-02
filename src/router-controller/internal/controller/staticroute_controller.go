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
	"net/http"
	"time"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/util/wait"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"

	productionstackv1alpha1 "github.com/vllm-project/production-stack/router-controller/api/v1alpha1"
)

// DynamicConfig represents the dynamic configuration for the vllm_router
type DynamicConfig struct {
	ServiceDiscovery string             `json:"service_discovery"`
	RoutingLogic     string             `json:"routing_logic"`
	StaticBackends   string             `json:"static_backends"`
	StaticModels     string             `json:"static_models"`
	HealthCheck      *HealthCheckConfig `json:"health_check,omitempty"`
}

// HealthCheckConfig represents the health check configuration for the vllm_router
type HealthCheckConfig struct {
	TimeoutSeconds   int32 `json:"timeout_seconds,omitempty"`
	PeriodSeconds    int32 `json:"period_seconds,omitempty"`
	SuccessThreshold int32 `json:"success_threshold,omitempty"`
	FailureThreshold int32 `json:"failure_threshold,omitempty"`
}

// StaticRouteReconciler reconciles a StaticRoute object
type StaticRouteReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

// +kubebuilder:rbac:groups=production-stack.vllm.ai,resources=staticroutes,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=production-stack.vllm.ai,resources=staticroutes/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=production-stack.vllm.ai,resources=staticroutes/finalizers,verbs=update
// +kubebuilder:rbac:groups=core,resources=configmaps,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=services,verbs=get;list;watch
// +kubebuilder:rbac:groups=core,resources=pods,verbs=get;list;watch

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
func (r *StaticRouteReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)
	logger.Info("Reconciling StaticRoute", "namespace", req.Namespace, "name", req.Name)

	// Fetch the StaticRoute instance
	staticRoute := &productionstackv1alpha1.StaticRoute{}
	err := r.Get(ctx, req.NamespacedName, staticRoute)
	if err != nil {
		if errors.IsNotFound(err) {
			// Request object not found, could have been deleted after reconcile request.
			// Return and don't requeue
			logger.Info("StaticRoute resource not found. Ignoring since object must be deleted")
			return ctrl.Result{}, nil
		}
		// Error reading the object - requeue the request.
		logger.Error(err, "Failed to get StaticRoute")
		return ctrl.Result{}, err
	}

	// Create or update the ConfigMap with the dynamic configuration
	configMap, err := r.reconcileConfigMap(ctx, staticRoute)
	if err != nil {
		logger.Error(err, "Failed to reconcile ConfigMap")
		return ctrl.Result{}, err
	}

	// Update the status with the ConfigMap reference
	if staticRoute.Status.ConfigMapRef != configMap.Name {
		staticRoute.Status.ConfigMapRef = configMap.Name
		now := metav1.Now()
		staticRoute.Status.LastAppliedTime = &now

		// Update the status
		if err := r.Status().Update(ctx, staticRoute); err != nil {
			logger.Error(err, "Failed to update StaticRoute status")
			return ctrl.Result{}, err
		}
	}

	// Check the router's health endpoint
	if err := r.checkRouterHealth(ctx, staticRoute); err != nil {
		logger.Error(err, "Failed to check router health")
		return ctrl.Result{}, err
	}

	// Determine requeue interval based on health check configuration
	requeueAfter := 5 * time.Minute // Default requeue interval
	if staticRoute.Spec.HealthCheck != nil && staticRoute.Spec.HealthCheck.PeriodSeconds > 0 {
		// Use the health check period as the requeue interval, but ensure it's not too frequent
		periodSeconds := staticRoute.Spec.HealthCheck.PeriodSeconds
		if periodSeconds < 60 {
			// If period is less than 60 seconds, use at least 1 minute to avoid too frequent reconciliations
			requeueAfter = 1 * time.Minute
		} else {
			requeueAfter = time.Duration(periodSeconds) * time.Second
		}
	}

	logger.Info("Reconciliation completed successfully", "requeueAfter", requeueAfter)
	return ctrl.Result{RequeueAfter: requeueAfter}, nil
}

// reconcileConfigMap creates or updates the ConfigMap with the dynamic configuration
func (r *StaticRouteReconciler) reconcileConfigMap(ctx context.Context, staticRoute *productionstackv1alpha1.StaticRoute) (*corev1.ConfigMap, error) {
	logger := log.FromContext(ctx)

	// Create the dynamic configuration
	dynamicConfig := DynamicConfig{
		ServiceDiscovery: staticRoute.Spec.ServiceDiscovery,
		RoutingLogic:     staticRoute.Spec.RoutingLogic,
		StaticBackends:   staticRoute.Spec.StaticBackends,
		StaticModels:     staticRoute.Spec.StaticModels,
	}

	// Convert the dynamic configuration to JSON
	dynamicConfigJSON, err := json.Marshal(dynamicConfig)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal dynamic configuration: %w", err)
	}

	// Determine the ConfigMap name
	configMapName := staticRoute.Spec.ConfigMapName
	if configMapName == "" {
		configMapName = fmt.Sprintf("%s-config", staticRoute.Name)
	}

	// Create or update the ConfigMap
	configMap := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      configMapName,
			Namespace: staticRoute.Namespace,
		},
	}

	// Set the owner reference
	if err := controllerutil.SetControllerReference(staticRoute, configMap, r.Scheme); err != nil {
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

// checkRouterHealth checks the health endpoint of the router
func (r *StaticRouteReconciler) checkRouterHealth(ctx context.Context, staticRoute *productionstackv1alpha1.StaticRoute) error {
	logger := log.FromContext(ctx)

	// List services that match the router selector or use the router reference
	services := &corev1.ServiceList{}

	if staticRoute.Spec.RouterRef != nil {
		// Use the RouterRef to directly access the service
		service := &corev1.Service{}
		serviceKey := client.ObjectKey{
			Name:      staticRoute.Spec.RouterRef.Name,
			Namespace: staticRoute.Spec.RouterRef.Namespace,
		}

		// If namespace is not specified, use the StaticRoute's namespace
		if serviceKey.Namespace == "" {
			serviceKey.Namespace = staticRoute.Namespace
		}

		err := r.Get(ctx, serviceKey, service)
		if err != nil {
			if errors.IsNotFound(err) {
				logger.Error(err, "Router service not found", "name", serviceKey.Name, "namespace", serviceKey.Namespace)
				return fmt.Errorf("router service %s/%s not found: %w", serviceKey.Namespace, serviceKey.Name, err)
			}
			return fmt.Errorf("failed to get router service: %w", err)
		}

		// Add the service to the list
		services.Items = append(services.Items, *service)
	}

	if len(services.Items) == 0 {
		logger.Info("No router services found")
		return nil
	}

	// Get health check configuration with defaults
	timeoutSeconds := int32(5)
	periodSeconds := int32(10)
	successThreshold := int32(1)
	failureThreshold := int32(3)

	if staticRoute.Spec.HealthCheck != nil {
		if staticRoute.Spec.HealthCheck.TimeoutSeconds > 0 {
			timeoutSeconds = staticRoute.Spec.HealthCheck.TimeoutSeconds
		}
		if staticRoute.Spec.HealthCheck.PeriodSeconds > 0 {
			periodSeconds = staticRoute.Spec.HealthCheck.PeriodSeconds
		}
		if staticRoute.Spec.HealthCheck.SuccessThreshold > 0 {
			successThreshold = staticRoute.Spec.HealthCheck.SuccessThreshold
		}
		if staticRoute.Spec.HealthCheck.FailureThreshold > 0 {
			failureThreshold = staticRoute.Spec.HealthCheck.FailureThreshold
		}
	}

	logger.Info("Using health check configuration",
		"timeoutSeconds", timeoutSeconds,
		"periodSeconds", periodSeconds,
		"successThreshold", successThreshold,
		"failureThreshold", failureThreshold)

	// Check the health endpoint of each router service
	for _, service := range services.Items {
		logger.Info("Checking health of router service", "namespace", service.Namespace, "name", service.Name)

		// Get the service port
		var port int32
		for _, p := range service.Spec.Ports {
			if p.Name == "http" || p.Name == "https" || p.Port == 8000 {
				port = p.Port
				break
			}
		}

		if port == 0 {
			logger.Info("No suitable port found for service", "namespace", service.Namespace, "name", service.Name)
			continue
		}

		// Check the health endpoint
		// Try to use the service's cluster IP directly instead of DNS name if CoreDNS is not working
		healthURL := ""
		if service.Spec.ClusterIP != "" && service.Spec.ClusterIP != "None" {
			healthURL = fmt.Sprintf("http://%s:%d/health", service.Spec.ClusterIP, port)
		} else {
			healthURL = fmt.Sprintf("http://%s.%s.svc.cluster.local:%d/health", service.Name, service.Namespace, port)
		}

		logger.Info("Checking health endpoint", "url", healthURL)

		// Create a client with a timeout
		client := &http.Client{
			Timeout: time.Duration(timeoutSeconds) * time.Second,
		}

		// Track consecutive successes and failures
		consecutiveSuccesses := int32(0)
		consecutiveFailures := int32(0)
		maxRetries := failureThreshold

		// Retry the health check based on configuration
		err := wait.PollUntilContextTimeout(ctx, time.Duration(periodSeconds)*time.Second, time.Duration(periodSeconds*maxRetries)*time.Second, false, func(ctx context.Context) (bool, error) {
			resp, err := client.Get(healthURL)
			if err != nil {
				logger.Error(err, "Failed to connect to health endpoint", "url", healthURL)
				consecutiveSuccesses = 0
				consecutiveFailures++
				if consecutiveFailures >= failureThreshold {
					return false, fmt.Errorf("health check failed after %d consecutive failures: %w", consecutiveFailures, err)
				}
				return false, nil
			}
			defer resp.Body.Close()
			logger.Info("Health endpoint returned status", "url", healthURL, "status", resp.StatusCode)
			if resp.StatusCode != http.StatusOK {
				logger.Info("Health endpoint returned non-OK status", "url", healthURL, "status", resp.StatusCode)
				consecutiveSuccesses = 0
				consecutiveFailures++
				if consecutiveFailures >= failureThreshold {
					return false, fmt.Errorf("health check failed after %d consecutive failures: status code %d", consecutiveFailures, resp.StatusCode)
				}
				return false, nil
			}

			logger.Info("Health endpoint check successful", "url", healthURL)
			consecutiveFailures = 0
			consecutiveSuccesses++
			return consecutiveSuccesses >= successThreshold, nil
		})

		if err != nil {
			logger.Error(err, "Health check failed after retries", "url", healthURL)
			// Update the status condition
			condition := metav1.Condition{
				Type:               "HealthCheckFailed",
				Status:             metav1.ConditionTrue,
				LastTransitionTime: metav1.Now(),
				Reason:             "HealthCheckFailed",
				Message:            fmt.Sprintf("Health check failed for service %s: %v", service.Name, err),
			}

			// Initialize conditions if nil
			if staticRoute.Status.Conditions == nil {
				staticRoute.Status.Conditions = []metav1.Condition{}
			}

			// Find and update or append the condition
			found := false
			for i, c := range staticRoute.Status.Conditions {
				if c.Type == condition.Type {
					staticRoute.Status.Conditions[i] = condition
					found = true
					break
				}
			}
			if !found {
				staticRoute.Status.Conditions = append(staticRoute.Status.Conditions, condition)
			}

			if err := r.Status().Update(ctx, staticRoute); err != nil {
				logger.Error(err, "Failed to update StaticRoute status")
				return err
			}
			return fmt.Errorf("health check failed for service %s: %w", service.Name, err)
		}

		// Update the status condition
		condition := metav1.Condition{
			Type:               "HealthCheckSucceeded",
			Status:             metav1.ConditionTrue,
			LastTransitionTime: metav1.Now(),
			Reason:             "HealthCheckSucceeded",
			Message:            fmt.Sprintf("Health check succeeded for service %s", service.Name),
		}

		// Initialize conditions if nil
		if staticRoute.Status.Conditions == nil {
			staticRoute.Status.Conditions = []metav1.Condition{}
		}

		// Find and update or append the condition
		found := false
		for i, c := range staticRoute.Status.Conditions {
			if c.Type == condition.Type {
				staticRoute.Status.Conditions[i] = condition
				found = true
				break
			}
		}
		if !found {
			staticRoute.Status.Conditions = append(staticRoute.Status.Conditions, condition)
		}

		if err := r.Status().Update(ctx, staticRoute); err != nil {
			logger.Error(err, "Failed to update StaticRoute status")
			return err
		}
	}

	return nil
}

// SetupWithManager sets up the controller with the Manager.
func (r *StaticRouteReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&productionstackv1alpha1.StaticRoute{}).
		Owns(&corev1.ConfigMap{}).
		Complete(r)
}
