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
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/builder"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/event"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	logf "sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/predicate"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	productionstackv1alpha1 "production-stack/api/v1alpha1"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

const (
	loraAdapterFinalizer = "loraadapter.production-stack.vllm.ai/finalizer"
)

// LoraAdapterReconciler reconciles a LoraAdapter object
type LoraAdapterReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

// +kubebuilder:rbac:groups=production-stack.vllm.ai,resources=loraadapters,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=production-stack.vllm.ai,resources=loraadapters/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=production-stack.vllm.ai,resources=loraadapters/finalizers,verbs=update
// +kubebuilder:rbac:groups=core,resources=pods,verbs=get;list;watch
// +kubebuilder:rbac:groups=core,resources=services,verbs=get;list;watch

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
// TODO(user): Modify the Reconcile function to compare the state specified by
// the LoraAdapter object against the actual cluster state, and then
// perform operations to make the cluster state reflect the state specified by
// the user.
//
// For more details, check Reconcile and its Result here:
// - https://pkg.go.dev/sigs.k8s.io/controller-runtime@v0.20.4/pkg/reconcile
func (r *LoraAdapterReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := logf.FromContext(ctx)
	logger.Info("Starting reconciliation loop")

	// Get all LoraAdapter instances
	loraAdapters := &productionstackv1alpha1.LoraAdapterList{}
	if err := r.List(ctx, loraAdapters); err != nil {
		logger.Error(err, "Failed to list LoraAdapter resources")
		return ctrl.Result{}, err
	}
	logger.Info("Found LoraAdapter resources", "count", len(loraAdapters.Items))

	// Track if any adapters are waiting for pods
	hasWaitingAdapters := false

	// Iterate through each LoraAdapter
	for _, loraAdapter := range loraAdapters.Items {
		logger.Info("Processing LoraAdapter", "namespace", loraAdapter.Namespace, "name", loraAdapter.Name)

		// Check if the adapter is being deleted
		if loraAdapter.DeletionTimestamp.IsZero() {
			logger.Info("Adding finalizer", "namespace", loraAdapter.Namespace, "name", loraAdapter.Name)
			if !controllerutil.ContainsFinalizer(&loraAdapter, loraAdapterFinalizer) {
				controllerutil.AddFinalizer(&loraAdapter, loraAdapterFinalizer)
				if err := r.Update(ctx, &loraAdapter); err != nil {
					logger.Error(err, "Failed to add finalizer",
						"namespace", loraAdapter.Namespace, "name", loraAdapter.Name)
					return ctrl.Result{}, err
				}
				// Get the latest version after update
				if err := r.Get(ctx, types.NamespacedName{
					Namespace: loraAdapter.Namespace,
					Name:      loraAdapter.Name,
				}, &loraAdapter); err != nil {
					logger.Error(err, "Failed to get latest LoraAdapter after adding finalizer",
						"namespace", loraAdapter.Namespace, "name", loraAdapter.Name)
					return ctrl.Result{}, err
				}
			}
		} else {
			// Handle deletion
			if err := r.handleDeletion(ctx, &loraAdapter); err != nil {
				logger.Error(err, "Failed to handle deletion",
					"namespace", loraAdapter.Namespace, "name", loraAdapter.Name)
				return ctrl.Result{}, err
			}
			continue
		}

		// Continue with normal reconciliation
		// Step 1: Get current state (adapter registrations)
		currentRegistrations, err := r.getAdapterRegistrations(ctx, &loraAdapter)
		if err != nil {
			logger.Error(err, "Failed to get current adapter registrations")
			return ctrl.Result{}, err
		}
		logger.Info("Current adapter registrations", "registrations", currentRegistrations,
			"namespace", loraAdapter.Namespace, "name", loraAdapter.Name)

		// Step 2: Update status with current registrations for this adapter
		if err := r.updateStatusWithRegistrations(ctx, &loraAdapter, currentRegistrations); err != nil {
			logger.Error(err, "Failed to update status with current registrations",
				"namespace", loraAdapter.Namespace, "name", loraAdapter.Name)
			continue // Continue with next adapter even if this one fails
		}
		logger.Info("Updated status with current registrations",
			"namespace", loraAdapter.Namespace, "name", loraAdapter.Name)

		// Step 3: Get desired state (optimal pod placements) for this adapter
		desiredPlacements, err := r.getOptimalPlacement(ctx, &loraAdapter)
		if err != nil {
			logger.Error(err, "Failed to get optimal pod placements",
				"namespace", loraAdapter.Namespace, "name", loraAdapter.Name)
			continue // Continue with next adapter even if this one fails
		}
		logger.Info("Desired pod placements", "placements", desiredPlacements,
			"namespace", loraAdapter.Namespace, "name", loraAdapter.Name)

		// Check if no pods are ready yet
		if len(desiredPlacements) == 0 {
			logger.Info("No pods are ready yet, waiting for pods to become ready",
				"namespace", loraAdapter.Namespace, "name", loraAdapter.Name)

			// Update status to reflect waiting state
			if err := r.updateStatusWithWaitingState(ctx, &loraAdapter, "Waiting for pods to become ready"); err != nil {
				logger.Error(err, "Failed to update status with waiting state",
					"namespace", loraAdapter.Namespace, "name", loraAdapter.Name)
				continue
			}

			// Mark that we have waiting adapters
			hasWaitingAdapters = true

			// Continue to next adapter
			continue
		}

		// Step 4: Compare current and desired state
		if needsReconciliation, err := r.compareStates(currentRegistrations, desiredPlacements); err != nil {
			logger.Error(err, "Failed to compare states",
				"namespace", loraAdapter.Namespace, "name", loraAdapter.Name)
			continue // Continue with next adapter even if this one fails
		} else if needsReconciliation {
			// Step 5: Reconcile to match desired state
			if err := r.reconcileToDesiredState(ctx, &loraAdapter, currentRegistrations, desiredPlacements); err != nil {
				logger.Error(err, "Failed to reconcile to desired state",
					"namespace", loraAdapter.Namespace, "name", loraAdapter.Name)
				continue // Continue with next adapter even if this one fails
			}
			logger.Info("Reconciled to desired state",
				"namespace", loraAdapter.Namespace, "name", loraAdapter.Name)

			// After reconciliation, get the latest state for this adapter
			if err := r.Get(ctx, types.NamespacedName{
				Namespace: loraAdapter.Namespace,
				Name:      loraAdapter.Name,
			}, &loraAdapter); err != nil {
				if errors.IsNotFound(err) {
					logger.Info("LoraAdapter resource not found. Ignoring since object must be deleted",
						"namespace", loraAdapter.Namespace, "name", loraAdapter.Name)
					continue
				}
				logger.Error(err, "Failed to get LoraAdapter",
					"namespace", loraAdapter.Namespace, "name", loraAdapter.Name)
				continue
			}

			// Get latest registrations after reconciliation
			latestRegistrations, err := r.getAdapterRegistrations(ctx, &loraAdapter)
			if err != nil {
				logger.Error(err, "Failed to get latest adapter registrations after reconciliation",
					"namespace", loraAdapter.Namespace, "name", loraAdapter.Name)
				continue
			}
			logger.Info("Latest adapter registrations", "registrations", latestRegistrations,
				"namespace", loraAdapter.Namespace, "name", loraAdapter.Name)

			// Update status with latest registrations
			if err := r.updateStatusWithRegistrations(ctx, &loraAdapter, latestRegistrations); err != nil {
				logger.Error(err, "Failed to update status with latest registrations",
					"namespace", loraAdapter.Namespace, "name", loraAdapter.Name)
				continue
			}
			logger.Info("Updated status with latest registrations",
				"namespace", loraAdapter.Namespace, "name", loraAdapter.Name)
		} else {
			logger.Info("No reconciliation needed",
				"namespace", loraAdapter.Namespace, "name", loraAdapter.Name)
		}
	}

	// Schedule periodic reconciliation based on whether we have waiting adapters
	logger.Info("Reconciliation loop completed")
	if hasWaitingAdapters {
		// If we have adapters waiting for pods, requeue more frequently
		logger.Info("Some adapters are waiting for pods, requeuing with shorter interval")
		return ctrl.Result{RequeueAfter: 30 * time.Second}, nil
	}
	return ctrl.Result{RequeueAfter: 5 * time.Minute}, nil
}

// SetupWithManager sets up the controller with the Manager.
func (r *LoraAdapterReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&productionstackv1alpha1.LoraAdapter{}).
		Watches(
			&corev1.Pod{},
			handler.EnqueueRequestsFromMapFunc(r.findLoraAdaptersForPod),
			builder.WithPredicates(predicate.Funcs{
				UpdateFunc: func(e event.UpdateEvent) bool {
					oldPod := e.ObjectOld.(*corev1.Pod)
					newPod := e.ObjectNew.(*corev1.Pod)
					// Trigger if pod becomes ready
					oldReady := false
					for _, cond := range oldPod.Status.Conditions {
						if cond.Type == corev1.PodReady {
							oldReady = cond.Status == corev1.ConditionTrue
							break
						}
					}
					newReady := false
					for _, cond := range newPod.Status.Conditions {
						if cond.Type == corev1.PodReady {
							newReady = cond.Status == corev1.ConditionTrue
							break
						}
					}
					return !oldReady && newReady
				},
				DeleteFunc: func(e event.DeleteEvent) bool {
					return true // Always trigger on deletion
				},
				GenericFunc: func(e event.GenericEvent) bool {
					return false // Don't trigger on generic events
				},
				CreateFunc: func(e event.CreateEvent) bool {
					return false // Don't trigger on creation
				},
			}),
		).
		Named("loraadapter").
		Complete(r)
}

// findLoraAdaptersForPod finds all LoraAdapters that should be reconciled when a pod changes
func (r *LoraAdapterReconciler) findLoraAdaptersForPod(ctx context.Context, pod client.Object) []reconcile.Request {
	// Check if the pod has the model label
	modelName, hasModel := pod.GetLabels()["model"]
	if !hasModel {
		return nil
	}

	// Get all LoraAdapters
	loraAdapters := &productionstackv1alpha1.LoraAdapterList{}
	if err := r.List(ctx, loraAdapters); err != nil {
		return nil
	}

	var requests []reconcile.Request
	for _, adapter := range loraAdapters.Items {
		// If the pod's model matches the adapter's base model, add it to the requests
		if adapter.Spec.BaseModel == modelName {
			requests = append(requests, reconcile.Request{
				NamespacedName: types.NamespacedName{
					Name:      adapter.Name,
					Namespace: adapter.Namespace,
				},
			})
		}
	}

	return requests
}

// discoverAdapter discovers the adapter from its source location
func (r *LoraAdapterReconciler) discoverAdapter(ctx context.Context, adapter *productionstackv1alpha1.LoraAdapter) (string, error) {
	source := adapter.Spec.AdapterSource

	// If path is already set, return it
	if source.AdapterPath != "" {
		return source.AdapterPath, nil
	}

	// Handle different source types
	switch source.Type {
	case "local":
		return "", fmt.Errorf("local adapter source requires AdapterPath to be set")
	case "s3":
		// TODO: Implement S3 discovery using credentials from CredentialsSecretRef
		return "", fmt.Errorf("S3 adapter discovery not implemented yet")
	case "http":
		// TODO: Implement HTTP discovery
		return "", fmt.Errorf("HTTP adapter discovery not implemented yet")
	case "huggingface":
		return r.downloadHuggingFaceAdapter(ctx, adapter)
	default:
		return "", fmt.Errorf("unsupported adapter source type: %s", source.Type)
	}
}

// downloadHuggingFaceAdapter downloads a LoRA adapter from HuggingFace Hub
func (r *LoraAdapterReconciler) downloadHuggingFaceAdapter(ctx context.Context, adapter *productionstackv1alpha1.LoraAdapter) (string, error) {
	logger := logf.Log.WithName("huggingface-download")

	source := adapter.Spec.AdapterSource

	// Validate required fields
	if source.Repository == nil || *source.Repository == "" {
		return "", fmt.Errorf("repository is required for huggingface adapter source")
	}

	// Verify whether the adapter is already downloaded
	if source.AdapterPath != "" {
		// Check if the adapter exists
		if _, err := os.Stat(source.AdapterPath); os.IsNotExist(err) {
			// If adapter doesn't exist, start download process
			logger.Info("Adapter not found at path, starting download", "path", source.AdapterPath)
			// Continue with download process instead of returning error
		} else {
			// Adapter exists, return the path
			return source.AdapterPath, nil
		}
	}

	// Download the adapter directly using command line tools
	adapterPath := filepath.Join("/data/shared-pvc-storage/lora-adapters", source.AdapterName)

	// Create the adapter directory if it doesn't exist
	if err := os.MkdirAll(adapterPath, 0755); err != nil {
		return "", fmt.Errorf("failed to create adapter directory: %w", err)
	}

	// Get the HuggingFace token from the secret
	secret := &corev1.Secret{}
	if err := r.Get(ctx, types.NamespacedName{
		Name:      source.CredentialsSecretRef.Name,
		Namespace: adapter.Namespace,
	}, secret); err != nil {
		return "", fmt.Errorf("failed to get secret: %w", err)
	}

	token, ok := secret.Data[source.CredentialsSecretRef.Key]
	if !ok {
		return "", fmt.Errorf("secret does not contain key %s", source.CredentialsSecretRef.Key)
	}

	// Download using huggingface-cli
	cmd := exec.CommandContext(ctx, "huggingface-cli", "download", *source.Repository, "--local-dir", adapterPath, "--token", string(token))
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("failed to download adapter with huggingface-cli: %w", err)
	}

	// Update the adapter path in the spec
	adapter.Spec.AdapterSource.AdapterPath = adapterPath
	if err := r.Update(ctx, adapter); err != nil {
		return "", fmt.Errorf("failed to update adapter path: %w", err)
	}

	logger.Info("Successfully downloaded HuggingFace adapter", "adapter", source.AdapterName, "path", adapter.Spec.AdapterSource.AdapterPath)
	return adapter.Spec.AdapterSource.AdapterPath, nil
}

// GetOptimalPlacement determines the optimal pod placement for an adapter
// TODO: Implement optimal placement logic, currently just returns all valid pods
func (r *LoraAdapterReconciler) getOptimalPlacement(ctx context.Context, adapter *productionstackv1alpha1.LoraAdapter) ([]PodPlacement, error) {
	// Get all vLLM pods in the cluster
	pods := &corev1.PodList{}
	if err := r.List(ctx, pods, client.MatchingLabels{
		"model": adapter.Spec.BaseModel,
	}); err != nil {
		return nil, fmt.Errorf("failed to list vLLM pods: %w", err)
	}

	// Filter for pods that are ready
	var validPods []corev1.Pod
	for _, pod := range pods.Items {
		// Check if pod is ready by looking at pod conditions
		for _, condition := range pod.Status.Conditions {
			if condition.Type == corev1.PodReady && condition.Status == corev1.ConditionTrue {
				validPods = append(validPods, pod)
				break
			}
		}
	}

	// If no pods are ready yet, return empty placement list instead of error
	// This allows the controller to continue processing and wait for pods to become ready
	if len(validPods) == 0 {
		return []PodPlacement{}, nil
	}

	// Determine number of pods to use
	numPods := len(validPods)
	if adapter.Spec.LoraAdapterDeploymentConfig.Replicas != nil {
		replicas := int(*adapter.Spec.LoraAdapterDeploymentConfig.Replicas)
		if replicas >= 0 {
			numPods = min(replicas, len(validPods))
		}
	}

	// Create placements
	var placements []PodPlacement
	for i := 0; i < numPods; i++ {
		placements = append(placements, PodPlacement{
			PodName:   validPods[i].Name,
			Namespace: validPods[i].Namespace,
		})
	}

	return placements, nil
}

// PodPlacement represents a pod where an adapter should be placed
type PodPlacement struct {
	PodName   string
	Namespace string
}

// getPodEndpoint gets the HTTP endpoint for a pod
func (r *LoraAdapterReconciler) getPodEndpoint(ctx context.Context, podName, namespace string, path string) (string, error) {
	// Get pod details
	pod := &corev1.Pod{}
	if err := r.Get(ctx, types.NamespacedName{
		Name:      podName,
		Namespace: namespace,
	}, pod); err != nil {
		return "", fmt.Errorf("failed to get pod: %w", err)
	}

	// Get pod IP
	if pod.Status.PodIP == "" {
		return "", fmt.Errorf("pod %s has no IP address", podName)
	}

	// Get container port
	port := 8000 // default port
	for _, container := range pod.Spec.Containers {
		for _, containerPort := range container.Ports {
			if containerPort.Name == "container-port" {
				port = int(containerPort.ContainerPort)
				break
			}
		}
	}

	// Construct endpoint URL using pod IP and container port
	return fmt.Sprintf("http://%s:%d%s", pod.Status.PodIP, port, path), nil
}

// sendRequest sends an HTTP request to the specified endpoint
func (r *LoraAdapterReconciler) sendRequest(ctx context.Context, method, endpoint string, payload interface{}, adapter *productionstackv1alpha1.LoraAdapter) ([]byte, error) {
	var bodyReader io.Reader
	if payload != nil {
		jsonData, err := json.Marshal(payload)
		if err != nil {
			return nil, fmt.Errorf("failed to marshal request payload: %w", err)
		}
		bodyReader = bytes.NewBuffer(jsonData)
	}

	// Create request
	req, err := http.NewRequestWithContext(ctx, method, endpoint, bodyReader)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	// Set headers
	req.Header.Set("Content-Type", "application/json")

	// Get API key
	apiKey, err := r.getVLLMApiKey(ctx, adapter)
	if err != nil {
		return nil, fmt.Errorf("failed to get API key: %w", err)
	}
	if apiKey != "" {
		req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", apiKey))
	}

	// Send request
	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	// Read response body
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response body: %w", err)
	}

	// Handle 400 status code specifically for already loaded adapters
	if resp.StatusCode == http.StatusBadRequest {
		var errorResponse struct {
			Message string `json:"message"`
			Type    string `json:"type"`
		}
		if err := json.Unmarshal(body, &errorResponse); err != nil {
			return nil, fmt.Errorf("failed to parse error response: %w", err)
		}

		// If the error indicates the adapter is already loaded, treat it as success
		if errorResponse.Type == "InvalidUserInput" &&
			strings.Contains(errorResponse.Message, "has already been loaded") {
			return body, nil
		}
	}

	// Check status code
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected status code: %d, body: %s", resp.StatusCode, string(body))
	}

	return body, nil
}

// getVLLMApiKey retrieves the vLLM API key from either direct value or secret reference
func (r *LoraAdapterReconciler) getVLLMApiKey(ctx context.Context, adapter *productionstackv1alpha1.LoraAdapter) (string, error) {
	if adapter.Spec.VLLMApiKey == nil {
		return "", nil
	}

	// If secret reference is provided, get the key from the secret
	if adapter.Spec.VLLMApiKey.SecretName != "" && adapter.Spec.VLLMApiKey.SecretKey != "" {
		secret := &corev1.Secret{}
		err := r.Get(ctx, types.NamespacedName{
			Name:      adapter.Spec.VLLMApiKey.SecretName,
			Namespace: adapter.Namespace,
		}, secret)
		if err != nil {
			return "", fmt.Errorf("failed to get secret: %w", err)
		}

		// Get the API key from the secret using the specified key
		apiKey, ok := secret.Data[adapter.Spec.VLLMApiKey.SecretKey]
		if !ok {
			return "", fmt.Errorf("secret does not contain key %s", adapter.Spec.VLLMApiKey.SecretKey)
		}

		return string(apiKey), nil
	}

	return "", nil
}

// loadAdapter loads a LoRA adapter on a specific pod
func (r *LoraAdapterReconciler) loadAdapter(ctx context.Context, podName, namespace, adapterPath string, adapter *productionstackv1alpha1.LoraAdapter) error {
	endpoint, err := r.getPodEndpoint(ctx, podName, namespace, "/v1/load_lora_adapter")
	if err != nil {
		return err
	}

	payload := map[string]string{
		"lora_name": adapter.Spec.AdapterSource.AdapterName,
		"lora_path": adapterPath,
	}

	_, err = r.sendRequest(ctx, "POST", endpoint, payload, adapter)
	return err
}

// unloadAdapter unloads a LoRA adapter from a specific pod
func (r *LoraAdapterReconciler) unloadAdapter(ctx context.Context, podName, namespace, adapterPath string, adapter *productionstackv1alpha1.LoraAdapter) error {
	endpoint, err := r.getPodEndpoint(ctx, podName, namespace, "/v1/unload_lora_adapter")
	if err != nil {
		return err
	}

	payload := map[string]string{
		"lora_name": adapter.Spec.AdapterSource.AdapterName,
	}

	_, err = r.sendRequest(ctx, "POST", endpoint, payload, adapter)
	return err
}

// getAdapterRegistrations gets the current adapter registrations from all pods
func (r *LoraAdapterReconciler) getAdapterRegistrations(ctx context.Context, adapter *productionstackv1alpha1.LoraAdapter) ([]productionstackv1alpha1.LoadedAdapter, error) {
	// Get all vLLM pods
	pods := &corev1.PodList{}
	if err := r.List(ctx, pods, client.HasLabels{"model"}); err != nil {
		return nil, fmt.Errorf("failed to list vLLM pods: %w", err)
	}
	logger := logf.FromContext(ctx)
	logger.Info("Found vLLM pods", "pods", len(pods.Items))

	var registrations []productionstackv1alpha1.LoadedAdapter
	for _, pod := range pods.Items {
		// Check if pod is ready by looking at pod conditions
		podReady := false
		for _, condition := range pod.Status.Conditions {
			if condition.Type == corev1.PodReady && condition.Status == corev1.ConditionTrue {
				podReady = true
				break
			}
		}
		if !podReady {
			logger.Info("Skipping pod", "pod", pod.Name, "namespace", pod.Namespace, "phase", pod.Status.Phase)
			continue
		}

		// Get pod endpoint
		endpoint, err := r.getPodEndpoint(ctx, pod.Name, pod.Namespace, "/v1/models")
		if err != nil {
			logger.Error(err, "Failed to get pod endpoint", "pod", pod.Name, "namespace", pod.Namespace)
			continue // Skip pods we can't reach
		}

		// Send GET request to get model list
		body, err := r.sendRequest(ctx, "GET", endpoint, nil, adapter)
		if err != nil {
			logger.Error(err, "Failed to get model list", "pod", pod.Name, "namespace", pod.Namespace)
			continue
		}

		var modelList struct {
			Object string `json:"object"`
			Data   []struct {
				ID      string  `json:"id"`
				Object  string  `json:"object"`
				Created int64   `json:"created"`
				OwnedBy string  `json:"owned_by"`
				Root    string  `json:"root"`
				Parent  *string `json:"parent"`
				// Add a catch-all field for any additional properties
				AdditionalFields map[string]interface{} `json:"-"`
			} `json:"data"`
		}

		if err := json.Unmarshal(body, &modelList); err != nil {
			logger.Error(err, "Failed to decode model list", "pod", pod.Name, "namespace", pod.Namespace)
			continue
		}

		// Add each LoRA adapter to registrations
		for _, model := range modelList.Data {
			// Skip base models (those without a parent)
			if model.Parent == nil {
				continue
			}

			// This is a LoRA adapter
			registrations = append(registrations, productionstackv1alpha1.LoadedAdapter{
				Name:     model.ID,
				Path:     model.Root,
				LoadTime: metav1.Unix(model.Created, 0),
				PodAssignments: productionstackv1alpha1.PodAssignment{
					PodName:   pod.Name,
					Namespace: pod.Namespace,
				},
				Status: "Loaded",
			})
		}
	}

	return registrations, nil
}

// updateStatusWithRegistrations updates the adapter status with current registrations
func (r *LoraAdapterReconciler) updateStatusWithRegistrations(ctx context.Context, adapter *productionstackv1alpha1.LoraAdapter, registrations []productionstackv1alpha1.LoadedAdapter) error {
	var updateErr error
	for retries := 0; retries < 3; retries++ {
		// Get the latest version before updating
		if err := r.Get(ctx, types.NamespacedName{
			Namespace: adapter.Namespace,
			Name:      adapter.Name,
		}, adapter); err != nil {
			return fmt.Errorf("failed to get latest LoraAdapter: %w", err)
		}

		// Update status with current registrations
		adapter.Status.LoadedAdapters = registrations
		adapter.Status.ObservedGeneration = adapter.Generation

		// Clear any waiting conditions since we now have registrations
		var updatedConditions []productionstackv1alpha1.Condition
		for _, condition := range adapter.Status.Conditions {
			if condition.Type != "WaitingForPods" {
				updatedConditions = append(updatedConditions, condition)
			}
		}
		adapter.Status.Conditions = updatedConditions

		// Try to update the status
		updateErr = r.Status().Update(ctx, adapter)
		if updateErr == nil {
			return nil
		}

		// If we get a conflict error, wait a bit and retry
		if errors.IsConflict(updateErr) {
			time.Sleep(time.Second * time.Duration(retries+1))
			continue
		}

		// If we get any other error, return it
		return fmt.Errorf("failed to update status with current registrations: %w", updateErr)
	}

	return fmt.Errorf("failed to update status with current registrations after retries: %w", updateErr)
}

// updateStatusWithWaitingState updates the adapter status when waiting for pods to become ready
func (r *LoraAdapterReconciler) updateStatusWithWaitingState(ctx context.Context, adapter *productionstackv1alpha1.LoraAdapter, message string) error {
	var updateErr error
	for retries := 0; retries < 3; retries++ {
		// Get the latest version before updating
		if err := r.Get(ctx, types.NamespacedName{
			Namespace: adapter.Namespace,
			Name:      adapter.Name,
		}, adapter); err != nil {
			return fmt.Errorf("failed to get latest LoraAdapter: %w", err)
		}

		// Update status to reflect waiting state
		adapter.Status.LoadedAdapters = []productionstackv1alpha1.LoadedAdapter{}
		adapter.Status.ObservedGeneration = adapter.Generation

		// Add a condition to indicate waiting state
		waitingCondition := productionstackv1alpha1.Condition{
			Type:               "WaitingForPods",
			Status:             "True",
			LastTransitionTime: metav1.Now(),
			Reason:             "NoReadyPods",
			Message:            message,
		}

		// Update or add the condition
		found := false
		for i, condition := range adapter.Status.Conditions {
			if condition.Type == "WaitingForPods" {
				adapter.Status.Conditions[i] = waitingCondition
				found = true
				break
			}
		}
		if !found {
			adapter.Status.Conditions = append(adapter.Status.Conditions, waitingCondition)
		}

		// Try to update the status
		updateErr = r.Status().Update(ctx, adapter)
		if updateErr == nil {
			return nil
		}

		// If we get a conflict error, wait a bit and retry
		if errors.IsConflict(updateErr) {
			time.Sleep(time.Second * time.Duration(retries+1))
			continue
		}

		// If we get any other error, return it
		return fmt.Errorf("failed to update status with waiting state: %w", updateErr)
	}

	return fmt.Errorf("failed to update status with waiting state after retries: %w", updateErr)
}

// compareStates compares current and desired states
func (r *LoraAdapterReconciler) compareStates(currentRegistrations []productionstackv1alpha1.LoadedAdapter, desiredPlacements []PodPlacement) (bool, error) {
	// Check if number of registrations matches expected
	if len(currentRegistrations) != len(desiredPlacements) {
		return true, nil
	}

	// Build map of desired placements for efficient lookup
	desiredMap := make(map[string]bool)
	for _, placement := range desiredPlacements {
		key := fmt.Sprintf("%s/%s", placement.Namespace, placement.PodName)
		desiredMap[key] = true
	}

	// Check if each current registration matches a desired placement
	for _, reg := range currentRegistrations {
		key := fmt.Sprintf("%s/%s", reg.PodAssignments.Namespace, reg.PodAssignments.PodName)
		if !desiredMap[key] {
			return true, nil
		}
	}

	return false, nil
}

// reconcileToDesiredState reconciles the current state to match the desired state
func (r *LoraAdapterReconciler) reconcileToDesiredState(ctx context.Context, adapter *productionstackv1alpha1.LoraAdapter, currentRegistrations []productionstackv1alpha1.LoadedAdapter, desiredPlacements []PodPlacement) error {
	logger := logf.FromContext(ctx)
	logger.Info("Reconciling to desired state", "adapter", adapter.Name)

	// Build maps for efficient lookup
	currentMap := make(map[string]productionstackv1alpha1.LoadedAdapter)
	desiredMap := make(map[string]bool)

	for _, reg := range currentRegistrations {
		key := fmt.Sprintf("%s/%s", reg.PodAssignments.Namespace, reg.PodAssignments.PodName)
		currentMap[key] = reg
	}

	for _, placement := range desiredPlacements {
		key := fmt.Sprintf("%s/%s", placement.Namespace, placement.PodName)
		desiredMap[key] = true
	}

	// Load adapters on missing pods
	for _, placement := range desiredPlacements {
		key := fmt.Sprintf("%s/%s", placement.Namespace, placement.PodName)
		if _, exists := currentMap[key]; !exists {
			logger.Info("Loading adapter on pod", "pod", placement.PodName, "namespace", placement.Namespace)
			adapterPath, err := r.discoverAdapter(ctx, adapter)
			if err != nil {
				return fmt.Errorf("failed to discover adapter: %w", err)
			}
			if err := r.loadAdapter(ctx, placement.PodName, placement.Namespace, adapterPath, adapter); err != nil {
				return fmt.Errorf("failed to load adapter on pod %s: %w", placement.PodName, err)
			}
		}
	}

	// Unload adapters from pods that shouldn't have them
	for key, reg := range currentMap {
		if !desiredMap[key] {
			logger.Info("Unloading adapter from pod", "pod", reg.PodAssignments.PodName, "namespace", reg.PodAssignments.Namespace)
			if err := r.unloadAdapter(ctx, reg.PodAssignments.PodName, reg.PodAssignments.Namespace, reg.Path, adapter); err != nil {
				return fmt.Errorf("failed to unload adapter from pod %s: %w", reg.PodAssignments.PodName, err)
			}
		}
	}

	return nil
}

// handleDeletion handles the deletion of a LoRA adapter
func (r *LoraAdapterReconciler) handleDeletion(ctx context.Context, adapter *productionstackv1alpha1.LoraAdapter) error {
	logger := logf.FromContext(ctx)
	logger.Info("Handling deletion of LoraAdapter",
		"namespace", adapter.Namespace, "name", adapter.Name)

	// Get current registrations to find where the adapter is loaded
	currentRegistrations, err := r.getAdapterRegistrations(ctx, adapter)
	if err != nil {
		return fmt.Errorf("failed to get current registrations: %w", err)
	}

	// Unload adapter from all pods where it's currently loaded
	for _, reg := range currentRegistrations {
		if reg.Name == adapter.Spec.AdapterSource.AdapterName {
			logger.Info("Unloading adapter from pod",
				"pod", reg.PodAssignments.PodName,
				"namespace", reg.PodAssignments.Namespace)

			if err := r.unloadAdapter(ctx,
				reg.PodAssignments.PodName,
				reg.PodAssignments.Namespace,
				reg.Path,
				adapter); err != nil {
				return fmt.Errorf("failed to unload adapter from pod %s: %w",
					reg.PodAssignments.PodName, err)
			}
		}
	}

	// Remove finalizer
	controllerutil.RemoveFinalizer(adapter, loraAdapterFinalizer)
	if err := r.Update(ctx, adapter); err != nil {
		return fmt.Errorf("failed to remove finalizer: %w", err)
	}

	logger.Info("Successfully cleaned up LoraAdapter",
		"namespace", adapter.Namespace, "name", adapter.Name)
	return nil
}
