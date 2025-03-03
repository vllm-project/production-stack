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
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"

	productionstackv1alpha1 "github.com/vllm-project/production-stack/router-controller/api/v1alpha1"
)

// BackendDynamicConfig represents the dynamic configuration for the vllm_router
// when using Backend CRD
type BackendDynamicConfig struct {
	ServiceDiscovery string `json:"service_discovery"`
	RoutingLogic     string `json:"routing_logic"`
	StaticBackends   string `json:"static_backends"`
	StaticModels     string `json:"static_models"`
	APIKey           string `json:"api_key,omitempty"`
}

// BackendReconciler reconciles a Backend object
type BackendReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

//+kubebuilder:rbac:groups=production-stack.vllm.ai,resources=backends,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=production-stack.vllm.ai,resources=backends/status,verbs=get;update;patch
//+kubebuilder:rbac:groups=production-stack.vllm.ai,resources=backends/finalizers,verbs=update
//+kubebuilder:rbac:groups=core,resources=services,verbs=get;list;watch
//+kubebuilder:rbac:groups=core,resources=configmaps,verbs=get;list;watch;create;update;patch;delete

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
func (r *BackendReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)
	logger.Info("Reconciling Backend", "name", req.NamespacedName)

	// Fetch the Backend instance
	backend := &productionstackv1alpha1.Backend{}
	err := r.Get(ctx, req.NamespacedName, backend)
	if err != nil {
		if errors.IsNotFound(err) {
			// Request object not found, could have been deleted after reconcile request.
			// Return and don't requeue
			logger.Info("Backend resource not found. Ignoring since object must be deleted")
			return ctrl.Result{}, nil
		}
		// Error reading the object - requeue the request.
		logger.Error(err, "Failed to get Backend")
		return ctrl.Result{}, err
	}

	// Initialize status if it's not set
	if backend.Status.Conditions == nil {
		backend.Status.Conditions = []metav1.Condition{}
	}

	// Validate the backend configuration
	if !r.validateBackendConfiguration(backend) {
		logger.Info("Invalid backend configuration")
		meta.SetStatusCondition(&backend.Status.Conditions, metav1.Condition{
			Type:               "ConfigurationValid",
			Status:             metav1.ConditionFalse,
			Reason:             "InvalidConfiguration",
			Message:            "Backend configuration is invalid",
			LastTransitionTime: metav1.Now(),
		})
		err = r.Status().Update(ctx, backend)
		if err != nil {
			logger.Error(err, "Failed to update Backend status")
			return ctrl.Result{}, err
		}
		return ctrl.Result{}, nil
	}

	// Check the backend's health
	isAvailable, err := r.checkBackendHealth(ctx, backend)
	if err != nil {
		logger.Error(err, "Failed to check backend health")
		// Update the status condition
		meta.SetStatusCondition(&backend.Status.Conditions, metav1.Condition{
			Type:               "Available",
			Status:             metav1.ConditionFalse,
			Reason:             "HealthCheckFailed",
			Message:            fmt.Sprintf("Health check failed: %v", err),
			LastTransitionTime: metav1.Now(),
		})
	} else if isAvailable {
		// Update the status condition
		meta.SetStatusCondition(&backend.Status.Conditions, metav1.Condition{
			Type:               "Available",
			Status:             metav1.ConditionTrue,
			Reason:             "HealthCheckSucceeded",
			Message:            "Backend is available",
			LastTransitionTime: metav1.Now(),
		})
	} else {
		// Update the status condition
		meta.SetStatusCondition(&backend.Status.Conditions, metav1.Condition{
			Type:               "Available",
			Status:             metav1.ConditionFalse,
			Reason:             "HealthCheckFailed",
			Message:            "Backend is not available",
			LastTransitionTime: metav1.Now(),
		})
	}

	// Update the status fields
	backend.Status.IsAvailable = isAvailable
	backend.Status.LastProbeTime = &metav1.Time{Time: time.Now()}

	// Handle secret reference if provided
	if backend.Spec.SecretRef != nil {
		// Get the secret
		secretNamespace := backend.Spec.SecretRef.Namespace
		if secretNamespace == "" {
			secretNamespace = backend.Namespace
		}

		secret := &corev1.Secret{}
		err := r.Get(ctx, client.ObjectKey{
			Name:      backend.Spec.SecretRef.Name,
			Namespace: secretNamespace,
		}, secret)

		if err != nil {
			if errors.IsNotFound(err) {
				logger.Info("Referenced Secret not found",
					"secret", backend.Spec.SecretRef.Name,
					"namespace", secretNamespace)
				meta.SetStatusCondition(&backend.Status.Conditions, metav1.Condition{
					Type:               "SecretAvailable",
					Status:             metav1.ConditionFalse,
					Reason:             "SecretNotFound",
					Message:            fmt.Sprintf("Secret %s not found in namespace %s", backend.Spec.SecretRef.Name, secretNamespace),
					LastTransitionTime: metav1.Now(),
				})
			} else {
				logger.Error(err, "Failed to get Secret")
				return ctrl.Result{}, err
			}
		} else {
			// Check if the API key exists in the secret
			_, ok := secret.Data[backend.Spec.SecretRef.Key]
			if !ok {
				logger.Info("API key not found in Secret",
					"secret", backend.Spec.SecretRef.Name,
					"key", backend.Spec.SecretRef.Key)
				meta.SetStatusCondition(&backend.Status.Conditions, metav1.Condition{
					Type:               "SecretAvailable",
					Status:             metav1.ConditionFalse,
					Reason:             "KeyNotFound",
					Message:            fmt.Sprintf("Key %s not found in Secret %s", backend.Spec.SecretRef.Key, backend.Spec.SecretRef.Name),
					LastTransitionTime: metav1.Now(),
				})
			} else {
				meta.SetStatusCondition(&backend.Status.Conditions, metav1.Condition{
					Type:               "SecretAvailable",
					Status:             metav1.ConditionTrue,
					Reason:             "SecretAvailable",
					Message:            "Secret is available",
					LastTransitionTime: metav1.Now(),
				})
			}
		}
	}

	// Update the Backend status
	if err := r.Status().Update(ctx, backend); err != nil {
		logger.Error(err, "Failed to update Backend status")
		return ctrl.Result{}, err
	}

	// Requeue after a period to check health again
	return ctrl.Result{RequeueAfter: 30 * time.Second}, nil
}

// reconcileConfigMap creates or updates the ConfigMap with the dynamic configuration
func (r *BackendReconciler) reconcileConfigMap(ctx context.Context, backend *productionstackv1alpha1.Backend) (*corev1.ConfigMap, error) {
	logger := log.FromContext(ctx)

	// Create a dynamic configuration for the backend
	dynamicConfig := &BackendDynamicConfig{
		ServiceDiscovery: "static",     // Default to static service discovery
		RoutingLogic:     "roundrobin", // Default to roundrobin
		StaticBackends:   r.getEndpointString(backend),
		StaticModels:     backend.Spec.Models,
	}

	// Handle secret reference if provided
	if backend.Spec.SecretRef != nil {
		// Get the secret
		secretNamespace := backend.Spec.SecretRef.Namespace
		if secretNamespace == "" {
			secretNamespace = backend.Namespace
		}

		secret := &corev1.Secret{}
		err := r.Get(ctx, client.ObjectKey{
			Name:      backend.Spec.SecretRef.Name,
			Namespace: secretNamespace,
		}, secret)

		if err != nil {
			if errors.IsNotFound(err) {
				logger.Info("Referenced Secret not found",
					"secret", backend.Spec.SecretRef.Name,
					"namespace", secretNamespace)
				meta.SetStatusCondition(&backend.Status.Conditions, metav1.Condition{
					Type:               "SecretAvailable",
					Status:             metav1.ConditionFalse,
					Reason:             "SecretNotFound",
					Message:            fmt.Sprintf("Secret %s not found in namespace %s", backend.Spec.SecretRef.Name, secretNamespace),
					LastTransitionTime: metav1.Now(),
				})
			} else {
				logger.Error(err, "Failed to get Secret")
				return nil, err
			}
		} else {
			// Get the API key from the secret
			apiKey, ok := secret.Data[backend.Spec.SecretRef.Key]
			if !ok {
				logger.Info("API key not found in Secret",
					"secret", backend.Spec.SecretRef.Name,
					"key", backend.Spec.SecretRef.Key)
				meta.SetStatusCondition(&backend.Status.Conditions, metav1.Condition{
					Type:               "SecretAvailable",
					Status:             metav1.ConditionFalse,
					Reason:             "KeyNotFound",
					Message:            fmt.Sprintf("Key %s not found in Secret %s", backend.Spec.SecretRef.Key, backend.Spec.SecretRef.Name),
					LastTransitionTime: metav1.Now(),
				})
			} else {
				// Set the API key in the dynamic configuration
				dynamicConfig.APIKey = string(apiKey)
				meta.SetStatusCondition(&backend.Status.Conditions, metav1.Condition{
					Type:               "SecretAvailable",
					Status:             metav1.ConditionTrue,
					Reason:             "SecretAvailable",
					Message:            "Secret is available",
					LastTransitionTime: metav1.Now(),
				})
			}
		}
	}

	// Convert the dynamic configuration to JSON
	dynamicConfigJSON, err := json.Marshal(dynamicConfig)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal dynamic configuration: %w", err)
	}

	// Determine the ConfigMap name
	configMapName := fmt.Sprintf("%s-backend-config", backend.Name)

	// Create or update the ConfigMap
	configMap := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      configMapName,
			Namespace: backend.Namespace,
		},
	}

	// Set the owner reference
	if err := controllerutil.SetControllerReference(backend, configMap, r.Scheme); err != nil {
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
func (r *BackendReconciler) getEndpointString(backend *productionstackv1alpha1.Backend) string {
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

// checkBackendHealth performs a health check on the backend
func (r *BackendReconciler) checkBackendHealth(ctx context.Context, backend *productionstackv1alpha1.Backend) (bool, error) {
	// TODO: Implement actual health check logic based on backend type
	// For now, just return true to indicate the backend is available
	return true, nil
}

// validateBackendConfiguration validates the backend configuration
func (r *BackendReconciler) validateBackendConfiguration(backend *productionstackv1alpha1.Backend) bool {
	// Check if endpoint is set and valid
	if r.getEndpointString(backend) == "" {
		return false
	}

	// Check if models is set
	if backend.Spec.Models == "" {
		return false
	}

	// Check if type is valid
	validTypes := map[string]bool{
		"vllm":   true,
		"openai": true,
		"ollama": true,
	}
	if !validTypes[backend.Spec.Type] {
		return false
	}

	// If secret reference is provided, validate it has required fields
	if backend.Spec.SecretRef != nil {
		if backend.Spec.SecretRef.Name == "" || backend.Spec.SecretRef.Key == "" {
			return false
		}
	}

	// For OpenAI backend type, secretRef is required
	if backend.Spec.Type == "openai" && backend.Spec.SecretRef == nil {
		return false
	}

	return true
}

// SetupWithManager sets up the controller with the Manager.
func (r *BackendReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&productionstackv1alpha1.Backend{}).
		Owns(&corev1.ConfigMap{}).
		Complete(r)
}
