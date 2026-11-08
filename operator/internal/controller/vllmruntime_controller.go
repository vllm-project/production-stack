/*
Copyright 2024.

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
	"maps"
	"reflect"
	"strconv"
	"strings"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/equality"
	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/intstr"
	"k8s.io/client-go/util/retry"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/log"

	productionstackv1alpha1 "production-stack/api/v1alpha1"
)

// VLLMRuntimeReconciler reconciles a VLLMRuntime object
type VLLMRuntimeReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

// +kubebuilder:rbac:groups=production-stack.vllm.ai,resources=vllmruntimes,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=production-stack.vllm.ai,resources=vllmruntimes/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=production-stack.vllm.ai,resources=vllmruntimes/finalizers,verbs=update
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=configmaps,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=services,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=persistentvolumeclaims,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=keda.sh,resources=scaledobjects,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=production-stack.vllm.ai,resources=vllmruntimes/scale,verbs=get;update;patch

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
func (r *VLLMRuntimeReconciler) Reconcile(
	ctx context.Context,
	req ctrl.Request,
) (ctrl.Result, error) {
	log := log.FromContext(ctx)

	// Fetch the VLLMRuntime instance
	vllmRuntime := &productionstackv1alpha1.VLLMRuntime{}
	err := r.Get(ctx, req.NamespacedName, vllmRuntime)
	if err != nil {
		if errors.IsNotFound(err) {
			// Request object not found, could have been deleted after reconcile request.
			// Return and don't requeue
			log.Info("VLLMRuntime resource not found. Ignoring since object must be deleted")
			return ctrl.Result{}, nil
		}
		// Error reading the object - requeue the request.
		log.Error(err, "Failed to get VLLMRuntime")
		return ctrl.Result{}, err
	}

	// Check if the service already exists, if not create a new one
	foundService := &corev1.Service{}
	err = r.Get(
		ctx,
		types.NamespacedName{Name: vllmRuntime.Name, Namespace: vllmRuntime.Namespace},
		foundService,
	)
	if err != nil && errors.IsNotFound(err) {
		// Define a new service
		svc := r.serviceForVLLMRuntime(vllmRuntime)
		log.Info(
			"Creating a new Service",
			"Service.Namespace",
			svc.Namespace,
			"Service.Name",
			svc.Name,
		)
		err = r.Create(ctx, svc)
		if err != nil {
			log.Error(
				err,
				"Failed to create new Service",
				"Service.Namespace",
				svc.Namespace,
				"Service.Name",
				svc.Name,
			)
			return ctrl.Result{}, err
		}
		// Service created successfully - return and requeue
		return ctrl.Result{Requeue: true}, nil
	} else if err != nil {
		log.Error(err, "Failed to get Service")
		return ctrl.Result{}, err
	}

	// Update the service if needed
	if r.serviceNeedsUpdate(foundService, vllmRuntime) {
		log.Info(
			"Updating Service",
			"Service.Namespace",
			foundService.Namespace,
			"Service.Name",
			foundService.Name,
		)
		// Create new service spec
		newSvc := r.serviceForVLLMRuntime(vllmRuntime)

		err = r.Update(ctx, newSvc)
		if err != nil {
			log.Error(
				err,
				"Failed to update Service",
				"Service.Namespace",
				foundService.Namespace,
				"Service.Name",
				foundService.Name,
			)
			return ctrl.Result{}, err
		}
		// Service updated successfully - return and requeue
		return ctrl.Result{Requeue: true}, nil
	}

	// Handle PVC if storage is enabled
	if vllmRuntime.Spec.StorageConfig.Enabled {
		// Check if the PVC already exists, if not create a new one
		foundPVC := &corev1.PersistentVolumeClaim{}
		err = r.Get(
			ctx,
			types.NamespacedName{Name: vllmRuntime.Name, Namespace: vllmRuntime.Namespace},
			foundPVC,
		)
		if err != nil && errors.IsNotFound(err) {
			// Define a new PVC
			pvc := r.pvcForVLLMRuntime(vllmRuntime)
			log.Info("Creating a new PVC", "PVC.Namespace", pvc.Namespace, "PVC.Name", pvc.Name)
			err = r.Create(ctx, pvc)
			if err != nil {
				log.Error(
					err,
					"Failed to create new PVC",
					"PVC.Namespace",
					pvc.Namespace,
					"PVC.Name",
					pvc.Name,
				)
				return ctrl.Result{}, err
			}
			// PVC created successfully - return and requeue
			return ctrl.Result{Requeue: true}, nil
		} else if err != nil {
			log.Error(err, "Failed to get PVC")
			return ctrl.Result{}, err
		}

		// Update the PVC if needed
		if r.pvcNeedsUpdate(foundPVC, vllmRuntime) {
			log.Info("Updating PVC", "PVC.Namespace", foundPVC.Namespace, "PVC.Name", foundPVC.Name)
			// Create new PVC spec
			newPVC := r.pvcForVLLMRuntime(vllmRuntime)

			err = r.Update(ctx, newPVC)
			if err != nil {
				log.Error(
					err,
					"Failed to update PVC",
					"PVC.Namespace",
					foundPVC.Namespace,
					"PVC.Name",
					foundPVC.Name,
				)
				return ctrl.Result{}, err
			}
			// PVC updated successfully - return and requeue
			return ctrl.Result{Requeue: true}, nil
		}
	}

	if vllmRuntime.Spec.Model.ChatTemplate != "" {
		foundCM := &corev1.ConfigMap{}
		err := r.Get(ctx, types.NamespacedName{
			Name:      vllmRuntime.Name + "-chat-template",
			Namespace: vllmRuntime.Namespace,
		}, foundCM)

		if err != nil {
			if errors.IsNotFound(err) {
				ct := r.configMapForVLLMRuntime(vllmRuntime)
				log.Info(
					"Creating a new ConfigMap",
					"ConfigMap.Namespace",
					ct.Namespace,
					"ConfigMap.Name",
					ct.Name,
				)

				if err := r.Create(ctx, ct); err != nil {
					log.Error(
						err,
						"failed to create new ConfigMap",
						"ConfigMap.Namespace",
						ct.Namespace,
						"ConfigMap.Name",
						ct.Name,
					)

					return ctrl.Result{}, err
				} else {
					return ctrl.Result{Requeue: true}, nil
				}
			}

			return ctrl.Result{}, err
		}

		if r.configMapNeedsUpdate(foundCM, vllmRuntime) {
			log.Info(
				"Updating ConfigMap",
				"ConfigMap.Namespace",
				foundCM.Namespace,
				"ConfigMap.Name",
				foundCM.Name,
			)

			newCT := r.configMapForVLLMRuntime(vllmRuntime)
			if err := r.Update(ctx, newCT); err != nil {
				log.Error(
					err,
					"failed to update ConfigMap",
					"cm.Namespace",
					foundCM.Namespace,
					"cm.Name",
					foundCM.Name,
				)

				return ctrl.Result{}, err
			}

			return ctrl.Result{Requeue: true}, nil
		}
	}

	// Check if the deployment already exists, if not create a new one
	found := &appsv1.Deployment{}
	err = r.Get(
		ctx,
		types.NamespacedName{Name: vllmRuntime.Name, Namespace: vllmRuntime.Namespace},
		found,
	)
	if err != nil && errors.IsNotFound(err) {
		// Define a new deployment
		dep := r.deploymentForVLLMRuntime(vllmRuntime)
		log.Info(
			"Creating a new Deployment",
			"Deployment.Namespace",
			dep.Namespace,
			"Deployment.Name",
			dep.Name,
		)
		err = r.Create(ctx, dep)
		if err != nil {
			log.Error(
				err,
				"Failed to create new Deployment",
				"Deployment.Namespace",
				dep.Namespace,
				"Deployment.Name",
				dep.Name,
			)
			return ctrl.Result{}, err
		}
		// Deployment created successfully - return and requeue
		return ctrl.Result{Requeue: true}, nil
	} else if err != nil {
		log.Error(err, "Failed to get Deployment")
		return ctrl.Result{}, err
	}

	// Update the deployment if needed
	if r.deploymentNeedsUpdate(ctx, found, vllmRuntime) {
		log.Info(
			"Updating Deployment",
			"Deployment.Namespace",
			found.Namespace,
			"Deployment.Name",
			found.Name,
		)
		// Create new deployment spec
		newDep := r.deploymentForVLLMRuntime(vllmRuntime)

		err = r.Update(ctx, newDep)
		if err != nil {
			log.Error(
				err,
				"Failed to update Deployment",
				"Deployment.Namespace",
				found.Namespace,
				"Deployment.Name",
				found.Name,
			)
			return ctrl.Result{}, err
		}
		// Deployment updated successfully - return and requeue
		return ctrl.Result{Requeue: true}, nil
	}

	// Create, update or delete KEDA ScaledObject
	if vllmRuntime.Spec.AutoscalingConfig != nil && vllmRuntime.Spec.AutoscalingConfig.Enabled {
		cfg := vllmRuntime.Spec.AutoscalingConfig
		if *cfg.MinReplicas > cfg.MaxReplicas {
			log.Error(nil, "Invalid autoscaling config: minReplicas must be <= maxReplicas",
				"minReplicas", *cfg.MinReplicas, "maxReplicas", cfg.MaxReplicas)
			return ctrl.Result{}, fmt.Errorf(
				"minReplicas (%d) must be <= maxReplicas (%d)",
				*cfg.MinReplicas,
				cfg.MaxReplicas,
			)
		}
		if cfg.MaxReplicas < vllmRuntime.Spec.DeploymentConfig.Replicas {
			log.Error(
				nil,
				"Invalid autoscaling config: maxReplicas must be >= deploymentConfig.replicas",
				"maxReplicas",
				cfg.MaxReplicas,
				"replicas",
				vllmRuntime.Spec.DeploymentConfig.Replicas,
			)
			return ctrl.Result{}, fmt.Errorf(
				"maxReplicas (%d) must be >= deploymentConfig.replicas (%d)",
				cfg.MaxReplicas,
				vllmRuntime.Spec.DeploymentConfig.Replicas,
			)
		}
		if err := r.reconcileScaledObject(ctx, vllmRuntime); err != nil {
			log.Error(err, "Failed to reconcile ScaledObject")
			return ctrl.Result{}, err
		}
	} else {
		scaledObject := &unstructured.Unstructured{}
		scaledObject.SetAPIVersion("keda.sh/v1alpha1")
		scaledObject.SetKind("ScaledObject")
		scaledObject.SetName(vllmRuntime.Name + "-scaledobject")
		scaledObject.SetNamespace(vllmRuntime.Namespace)
		// Best-effort cleanup of a stale ScaledObject when autoscaling is
		// disabled. Tolerate IsNoMatchError so the reconcile still succeeds on
		// clusters where KEDA is not installed (the keda.sh API group is not
		// registered): there is nothing to delete, and requiring KEDA here
		// would make the operator unusable on non-autoscaling clusters.
		if err := r.Delete(ctx, scaledObject); err != nil &&
			!errors.IsNotFound(err) && !meta.IsNoMatchError(err) {
			log.Error(err, "Failed to delete ScaledObject")
			return ctrl.Result{}, err
		}
	}

	// Update the status
	if err := r.updateStatus(ctx, vllmRuntime, found); err != nil {
		log.Error(err, "Failed to update VLLMRuntime status")
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, nil
}

// maxModelLenArg renders the --max-model-len value and reports whether the
// flag should be passed at all.
//
// The field is int-or-string because vLLM accepts a plain count, the sentinels
// "auto" and -1 for deriving it from the model config, and suffixed forms such
// as "32k". An unset field is the integer zero, which means "leave it to vLLM"
// rather than a context length of nothing.
func maxModelLenArg(maxModelLen intstr.IntOrString) (string, bool) {
	if maxModelLen.Type == intstr.String {
		if maxModelLen.StrVal == "" {
			return "", false
		}
		return maxModelLen.StrVal, true
	}
	if maxModelLen.IntVal == 0 {
		return "", false
	}
	return strconv.Itoa(int(maxModelLen.IntVal)), true
}

// kvTransferConfigArg returns the value following --kv-transfer-config in args,
// or the empty string when the flag is absent.
func kvTransferConfigArg(args []string) string {
	for i, arg := range args {
		if arg == "--kv-transfer-config" && i+1 < len(args) {
			return args[i+1]
		}
	}
	return ""
}

// lmcacheEnvValues picks the in-process LMCache settings out of a container's
// env, for comparing the expected and the running Deployment.
func lmcacheEnvValues(env []corev1.EnvVar) map[string]string {
	values := map[string]string{}
	for _, e := range env {
		switch e.Name {
		case "LMCACHE_USE_EXPERIMENTAL",
			"LMCACHE_LOCAL_CPU", "LMCACHE_MAX_LOCAL_CPU_SIZE",
			"LMCACHE_LOCAL_DISK", "LMCACHE_MAX_LOCAL_DISK_SIZE",
			"LMCACHE_REMOTE_URL", "LMCACHE_REMOTE_SERDE":
			values[e.Name] = e.Value
		}
	}
	return values
}

// kvTransferConfig is the --kv-transfer-config document passed to vllm serve.
type kvTransferConfig struct {
	KVConnector string `json:"kv_connector"`
	KVRole      string `json:"kv_role"`
	// ExtraConfig is omitted for the local connectors, which take no extra
	// configuration.
	ExtraConfig map[string]any `json:"kv_connector_extra_config,omitempty"`
}

// isLMCacheMultiprocess reports whether the runtime attaches to a CacheServer
// rather than keeping its LMCache in process. Multiprocess is the API default,
// so an empty mode, from an object that bypassed defaulting, counts as
// Multiprocess too; only an explicit InProcess keeps the cache in process.
func isLMCacheMultiprocess(vllmRuntime *productionstackv1alpha1.VLLMRuntime) bool {
	return vllmRuntime.Spec.LMCacheConfig.Mode != productionstackv1alpha1.LMCacheModeInProcess
}

// lmcacheKVTransferConfig renders the --kv-transfer-config value for a runtime.
//
// InProcess mode selects the in-process connector, LMCacheConnectorV1 or, for
// the legacy engine, LMCacheConnector, and renders exactly the document main
// always has, so existing runtimes do not roll. Multiprocess mode selects the
// LMCacheMPConnector, with the cache server address and transfer mode in the
// extra config.
//
// Args:
//
//	vllmRuntime: The runtime whose LMCacheConfig is rendered.
//
// Returns:
//
//	The JSON document.
func lmcacheKVTransferConfig(
	vllmRuntime *productionstackv1alpha1.VLLMRuntime,
) string {
	lmCache := vllmRuntime.Spec.LMCacheConfig

	if !isLMCacheMultiprocess(vllmRuntime) {
		connector := "LMCacheConnector"
		if vllmRuntime.Spec.VLLMConfig.V1 {
			connector = "LMCacheConnectorV1"
		}
		// Marshalling cannot fail: both values are strings.
		encoded, _ := json.Marshal(kvTransferConfig{KVConnector: connector, KVRole: "kv_both"})
		return string(encoded)
	}

	mp := lmCache.Multiprocess
	extra := map[string]any{}
	if mp.Host != "" {
		extra["lmcache.mp.host"] = mp.Host
	}
	if mp.Port > 0 {
		extra["lmcache.mp.port"] = mp.Port
	}
	extra["lmcache.mp.mp_transfer_mode"] = mpTransferMode(mp.TransferMode)
	if mp.IsolatedIPC {
		extra["lmcache.mp.isolated_ipc"] = true
	}
	// User-supplied entries win, so an escape hatch exists for keys the spec
	// does not model, including overrides of the generated ones.
	for key, value := range mp.ExtraConfig {
		extra[key] = value
	}

	config := kvTransferConfig{
		KVConnector: "LMCacheMPConnector",
		KVRole:      "kv_both",
		ExtraConfig: extra,
	}
	// Marshalling cannot fail: every value is a string, an int32 or a bool.
	encoded, _ := json.Marshal(config)
	return string(encoded)
}

// inProcessLMCacheEnv renders the in-process LMCache settings as the
// environment variables LMCache reads, in the same form main always has.
func inProcessLMCacheEnv(lmCache productionstackv1alpha1.LMCacheConfig) []corev1.EnvVar {
	var env []corev1.EnvVar
	if lmCache.CPUOffloadingBufferSize != "" {
		env = append(env,
			corev1.EnvVar{Name: "LMCACHE_LOCAL_CPU", Value: "True"},
			corev1.EnvVar{Name: "LMCACHE_MAX_LOCAL_CPU_SIZE", Value: lmCache.CPUOffloadingBufferSize},
		)
	}
	if lmCache.DiskOffloadingBufferSize != "" {
		env = append(env,
			corev1.EnvVar{Name: "LMCACHE_LOCAL_DISK", Value: "True"},
			corev1.EnvVar{Name: "LMCACHE_MAX_LOCAL_DISK_SIZE", Value: lmCache.DiskOffloadingBufferSize},
		)
	}
	if lmCache.RemoteURL != "" {
		env = append(env,
			corev1.EnvVar{Name: "LMCACHE_REMOTE_URL", Value: lmCache.RemoteURL},
			corev1.EnvVar{Name: "LMCACHE_REMOTE_SERDE", Value: lmCache.RemoteSerde},
		)
	}
	return env
}

// deploymentForVLLMRuntime returns a VLLMRuntime Deployment object
func (r *VLLMRuntimeReconciler) deploymentForVLLMRuntime(
	vllmRuntime *productionstackv1alpha1.VLLMRuntime,
) *appsv1.Deployment {
	labels := map[string]string{"app": vllmRuntime.Name}
	maps.Copy(labels, vllmRuntime.Labels)

	// Define probes
	readinessProbe := &corev1.Probe{
		ProbeHandler: corev1.ProbeHandler{
			HTTPGet: &corev1.HTTPGetAction{
				Path:   "/health",
				Port:   intstr.FromInt(int(vllmRuntime.Spec.VLLMConfig.Port)),
				Scheme: corev1.URISchemeHTTP,
			},
		},
		InitialDelaySeconds: 10,
		PeriodSeconds:       20,
		TimeoutSeconds:      5,
		SuccessThreshold:    1,
		FailureThreshold:    10,
	}

	livenessProbe := &corev1.Probe{
		ProbeHandler: corev1.ProbeHandler{
			HTTPGet: &corev1.HTTPGetAction{
				Path:   "/health",
				Port:   intstr.FromInt(int(vllmRuntime.Spec.VLLMConfig.Port)),
				Scheme: corev1.URISchemeHTTP,
			},
		},
		InitialDelaySeconds: 10,
		PeriodSeconds:       20,
		TimeoutSeconds:      3,
		SuccessThreshold:    1,
		FailureThreshold:    10,
	}

	startupProbe := &corev1.Probe{
		ProbeHandler: corev1.ProbeHandler{
			HTTPGet: &corev1.HTTPGetAction{
				Path:   "/health",
				Port:   intstr.FromInt(int(vllmRuntime.Spec.VLLMConfig.Port)),
				Scheme: corev1.URISchemeHTTP,
			},
		},
		InitialDelaySeconds: 120,
		PeriodSeconds:       20,
		TimeoutSeconds:      3,
		FailureThreshold:    100,
	}

	// Build command line arguments
	args := []string{
		vllmRuntime.Spec.Model.ModelURL,
		"--host",
		"0.0.0.0",
		"--port",
		fmt.Sprintf("%d", vllmRuntime.Spec.VLLMConfig.Port),
	}

	if vllmRuntime.Spec.Model.EnableLoRA {
		args = append(args, "--enable-lora")
	}

	if vllmRuntime.Spec.Model.EnableTool {
		args = append(args, "--enable-auto-tool-choice")
	}

	if vllmRuntime.Spec.Model.ToolCallParser != "" {
		args = append(args, "--tool-call-parser", vllmRuntime.Spec.Model.ToolCallParser)
	}

	if vllmRuntime.Spec.Model.ReasoningParser != "" {
		args = append(args, "--reasoning-parser", vllmRuntime.Spec.Model.ReasoningParser)
	}

	if vllmRuntime.Spec.Model.TrustRemoteCode {
		args = append(args, "--trust-remote-code")
	}

	if vllmRuntime.Spec.VLLMConfig.EnableChunkedPrefill {
		args = append(args, "--enable-chunked-prefill")
	} else {
		args = append(args, "--no-enable-chunked-prefill")
	}

	if vllmRuntime.Spec.VLLMConfig.EnablePrefixCaching {
		args = append(args, "--enable-prefix-caching")
	} else {
		args = append(args, "--no-enable-prefix-caching")
	}

	if maxModelLen, ok := maxModelLenArg(vllmRuntime.Spec.Model.MaxModelLen); ok {
		args = append(args, "--max-model-len", maxModelLen)
	}

	if vllmRuntime.Spec.Model.DType != "" {
		args = append(args, "--dtype", vllmRuntime.Spec.Model.DType)
	}

	if vllmRuntime.Spec.VLLMConfig.TensorParallelSize > 0 {
		args = append(
			args,
			"--tensor-parallel-size",
			fmt.Sprintf("%d", vllmRuntime.Spec.VLLMConfig.TensorParallelSize),
		)
	}

	if vllmRuntime.Spec.Model.MaxNumSeqs > 0 {
		args = append(args, "--max-num-seqs", fmt.Sprintf("%d", vllmRuntime.Spec.Model.MaxNumSeqs))
	}

	if vllmRuntime.Spec.VLLMConfig.GpuMemoryUtilization != "" {
		args = append(
			args,
			"--gpu-memory-utilization",
			vllmRuntime.Spec.VLLMConfig.GpuMemoryUtilization,
		)
	}

	if vllmRuntime.Spec.VLLMConfig.MaxLoras > 0 {
		args = append(args, "--max_loras", fmt.Sprintf("%d", vllmRuntime.Spec.VLLMConfig.MaxLoras))
	}

	if vllmRuntime.Spec.VLLMConfig.MaxNumBatchedTokens > 0 {
		args = append(
			args,
			"--max-num-batched-tokens",
			fmt.Sprintf("%d", vllmRuntime.Spec.VLLMConfig.MaxNumBatchedTokens),
		)
	}

	if vllmRuntime.Spec.VLLMConfig.ExtraArgs != nil {
		args = append(args, vllmRuntime.Spec.VLLMConfig.ExtraArgs...)
	}

	if vllmRuntime.Spec.Model.ChatTemplate != "" {
		args = append(args, "--chat-template", "/etc/chat-template.json")
	}

	// Build environment variables
	env := []corev1.EnvVar{}
	if vllmRuntime.Spec.VLLMConfig.V1 {
		env = append(env, corev1.EnvVar{
			Name:  "VLLM_USE_V1",
			Value: "1",
		})
	} else {
		env = append(env, corev1.EnvVar{
			Name:  "VLLM_USE_V1",
			Value: "0",
		})
	}

	if vllmRuntime.Spec.Model.EnableLoRA {
		env = append(env,
			corev1.EnvVar{
				Name:  "VLLM_ALLOW_RUNTIME_LORA_UPDATING",
				Value: "True",
			},
		)
	}

	// LM Cache configuration
	if vllmRuntime.Spec.LMCacheConfig.Enabled {
		env = append(env,
			corev1.EnvVar{
				Name:  "LMCACHE_LOG_LEVEL",
				Value: "DEBUG",
			},
		)
		if !isLMCacheMultiprocess(vllmRuntime) {
			env = append(env, corev1.EnvVar{
				Name:  "LMCACHE_USE_EXPERIMENTAL",
				Value: "True",
			})
		}
		env = append(env, corev1.EnvVar{
			Name:  "VLLM_RPC_TIMEOUT",
			Value: "1000000",
		})

		args = append(args, "--kv-transfer-config", lmcacheKVTransferConfig(vllmRuntime))

		// The offloading and remote settings configure the cache inside the
		// engine process. In Multiprocess mode the cache lives in the
		// CacheServer instead, so they are not rendered even though the API
		// still fills in their defaults.
		if !isLMCacheMultiprocess(vllmRuntime) {
			env = append(env, inProcessLMCacheEnv(vllmRuntime.Spec.LMCacheConfig)...)
		}
	}

	// Add user-defined environment variables
	if vllmRuntime.Spec.VLLMConfig.Env != nil {
		for _, e := range vllmRuntime.Spec.VLLMConfig.Env {
			env = append(env, corev1.EnvVar{
				Name:  e.Name,
				Value: e.Value,
			})
		}
	}

	// Build resource requirements
	resources := corev1.ResourceRequirements{
		Requests: corev1.ResourceList{},
		Limits:   corev1.ResourceList{},
	}

	if vllmRuntime.Spec.DeploymentConfig.Resources.CPU != "" {
		resources.Requests[corev1.ResourceCPU] = resource.MustParse(
			vllmRuntime.Spec.DeploymentConfig.Resources.CPU,
		)
		resources.Limits[corev1.ResourceCPU] = resource.MustParse(
			vllmRuntime.Spec.DeploymentConfig.Resources.CPU,
		)
	}

	if vllmRuntime.Spec.DeploymentConfig.Resources.Memory != "" {
		resources.Requests[corev1.ResourceMemory] = resource.MustParse(
			vllmRuntime.Spec.DeploymentConfig.Resources.Memory,
		)
		resources.Limits[corev1.ResourceMemory] = resource.MustParse(
			vllmRuntime.Spec.DeploymentConfig.Resources.Memory,
		)
	}

	if vllmRuntime.Spec.DeploymentConfig.Resources.GPU != "" {
		// Parse GPU resource as a decimal value
		// Determine which GPU type to use (default nvidia.com/gpu)
		gpuType := "nvidia.com/gpu"
		if vllmRuntime.Spec.DeploymentConfig.Resources.GPUType != "" {
			gpuType = vllmRuntime.Spec.DeploymentConfig.Resources.GPUType
		}
		gpuResource := resource.MustParse(vllmRuntime.Spec.DeploymentConfig.Resources.GPU)
		resources.Requests[corev1.ResourceName(gpuType)] = gpuResource
		resources.Limits[corev1.ResourceName(gpuType)] = gpuResource
	}

	// Get the image from Image spec or use default
	image := vllmRuntime.Spec.DeploymentConfig.Image.Registry + "/" + vllmRuntime.Spec.DeploymentConfig.Image.Name

	// Get the image pull policy
	imagePullPolicy := corev1.PullIfNotPresent
	if vllmRuntime.Spec.DeploymentConfig.Image.PullPolicy != "" {
		imagePullPolicy = corev1.PullPolicy(vllmRuntime.Spec.DeploymentConfig.Image.PullPolicy)
	}

	// Build image pull secrets
	var imagePullSecrets []corev1.LocalObjectReference
	if vllmRuntime.Spec.DeploymentConfig.Image.PullSecretName != "" {
		imagePullSecrets = append(imagePullSecrets, corev1.LocalObjectReference{
			Name: vllmRuntime.Spec.DeploymentConfig.Image.PullSecretName,
		})
	}

	if vllmRuntime.Spec.Model.HFTokenSecret.HFTokenSecretName != "" {
		env = append(env, corev1.EnvVar{
			Name: "HF_TOKEN",
			ValueFrom: &corev1.EnvVarSource{
				SecretKeyRef: &corev1.SecretKeySelector{
					LocalObjectReference: corev1.LocalObjectReference{
						Name: vllmRuntime.Spec.Model.HFTokenSecret.HFTokenSecretName,
					},
					Key: vllmRuntime.Spec.Model.HFTokenSecret.HFTokenKeyName,
				},
			},
		})
	}

	// Build volumes and volume mounts if storage is enabled
	var volumes []corev1.Volume
	var volumeMounts []corev1.VolumeMount

	if vllmRuntime.Spec.StorageConfig.Enabled {
		volumeName := "pvc-storage"
		if vllmRuntime.Spec.StorageConfig.VolumeName != "" {
			volumeName = vllmRuntime.Spec.StorageConfig.VolumeName
		}

		mountPath := "/data"
		if vllmRuntime.Spec.StorageConfig.MountPath != "" {
			mountPath = vllmRuntime.Spec.StorageConfig.MountPath
		}

		volumes = append(volumes, corev1.Volume{
			Name: volumeName,
			VolumeSource: corev1.VolumeSource{
				PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{
					ClaimName: vllmRuntime.Name,
				},
			},
		})

		volumeMounts = append(volumeMounts, corev1.VolumeMount{
			Name:      volumeName,
			MountPath: mountPath,
		})
	}

	if vllmRuntime.Spec.Model.ChatTemplate != "" {
		volumeName := "chat-template"
		mountPath := "/etc/chat-template.json"

		volumes = append(volumes, corev1.Volume{
			Name: volumeName,
			VolumeSource: corev1.VolumeSource{
				ConfigMap: &corev1.ConfigMapVolumeSource{
					LocalObjectReference: corev1.LocalObjectReference{
						Name: vllmRuntime.Name + "-" + volumeName,
					},
					Items: []corev1.KeyToPath{
						{
							Key:  "chatTemplate",
							Path: "chat_template.json",
						},
					},
				},
			},
		})

		volumeMounts = append(volumeMounts, corev1.VolumeMount{
			Name:      volumeName,
			MountPath: mountPath,
			SubPath:   "chat_template.json",
		})
	}

	// Mount an emptyDir (medium=Memory) at /dev/shm when a size is requested.
	// Tensor parallelism communicates over shared memory, and the container
	// default /dev/shm is usually too small for it.
	// hostIPC already replaces /dev/shm with the host's tmpfs, which is the
	// point of enabling it, so an emptyDir would mask the segment the cache
	// server shares.
	if vllmRuntime.Spec.DeploymentConfig.ShmSize != "" &&
		!vllmRuntime.Spec.DeploymentConfig.HostIPC {
		shmSource := corev1.VolumeSource{
			EmptyDir: &corev1.EmptyDirVolumeSource{Medium: corev1.StorageMediumMemory},
		}
		if q, err := resource.ParseQuantity(vllmRuntime.Spec.DeploymentConfig.ShmSize); err == nil {
			shmSource.EmptyDir.SizeLimit = &q
		} else {
			// Don't silently mount an unbounded /dev/shm on a typo: surface the
			// bad value so the misconfiguration is visible instead of defaulting
			// to the node's memory limit without any indication.
			log.Log.Error(err, "Invalid shmSize; mounting /dev/shm without a size limit",
				"vllmRuntime", vllmRuntime.Name,
				"shmSize", vllmRuntime.Spec.DeploymentConfig.ShmSize)
		}
		volumes = append(volumes, corev1.Volume{Name: "dshm", VolumeSource: shmSource})
		volumeMounts = append(volumeMounts, corev1.VolumeMount{
			Name:      "dshm",
			MountPath: "/dev/shm",
		})
	}

	var affinity *corev1.Affinity

	if vllmRuntime.Spec.DeploymentConfig.NodeSelectorTerms != nil {
		affinity = &corev1.Affinity{
			NodeAffinity: &corev1.NodeAffinity{
				RequiredDuringSchedulingIgnoredDuringExecution: &corev1.NodeSelector{
					NodeSelectorTerms: vllmRuntime.Spec.DeploymentConfig.NodeSelectorTerms,
				},
			},
		}
	}

	containers := []corev1.Container{
		{
			Name:            "vllm",
			Image:           image,
			ImagePullPolicy: imagePullPolicy,
			Command:         []string{"/opt/venv/bin/vllm", "serve"},
			Args:            args,
			Env:             env,
			Ports: []corev1.ContainerPort{
				{
					Name:          "http",
					ContainerPort: vllmRuntime.Spec.VLLMConfig.Port,
				},
			},
			Resources:      resources,
			VolumeMounts:   volumeMounts,
			ReadinessProbe: readinessProbe,
			StartupProbe:   startupProbe,
			LivenessProbe:  livenessProbe,
		},
	}

	if vllmRuntime.Spec.DeploymentConfig.SidecarConfig.Enabled {
		containers = append(containers, r.buildSidecarContainer(vllmRuntime))
	}

	dep := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      vllmRuntime.Name,
			Namespace: vllmRuntime.Namespace,
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &vllmRuntime.Spec.DeploymentConfig.Replicas,
			Strategy: appsv1.DeploymentStrategy{
				Type: appsv1.DeploymentStrategyType(
					vllmRuntime.Spec.DeploymentConfig.DeployStrategy,
				),
			},
			Selector: &metav1.LabelSelector{
				MatchLabels: labels,
			},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels:      labels,
					Annotations: vllmRuntime.Spec.DeploymentConfig.PodAnnotations,
				},
				Spec: corev1.PodSpec{
					RuntimeClassName: runtimeClassOrNil(vllmRuntime.Spec.DeploymentConfig.RuntimeClass),
					HostIPC:          vllmRuntime.Spec.DeploymentConfig.HostIPC,
					Affinity:         affinity,
					Tolerations:      vllmRuntime.Spec.DeploymentConfig.Toleration,
					ImagePullSecrets: imagePullSecrets,
					Volumes:          volumes,
					Containers:       containers,
				},
			},
		},
	}

	// Set the owner reference
	ctrl.SetControllerReference(vllmRuntime, dep, r.Scheme)
	return dep
}

// buildSidecarContainer builds the sidecar container configuration
func (r *VLLMRuntimeReconciler) buildSidecarContainer(
	vllmRuntime *productionstackv1alpha1.VLLMRuntime,
) corev1.Container {
	sidecarConfig := vllmRuntime.Spec.DeploymentConfig.SidecarConfig

	// Build sidecar volume mounts
	var sidecarVolumeMounts []corev1.VolumeMount

	mountPath := "/data"

	// Add shared storage volume mount if storage is enabled
	if vllmRuntime.Spec.StorageConfig.Enabled {
		volumeName := "pvc-storage"
		if vllmRuntime.Spec.StorageConfig.VolumeName != "" {
			volumeName = vllmRuntime.Spec.StorageConfig.VolumeName
		}

		if sidecarConfig.MountPath != "" {
			mountPath = sidecarConfig.MountPath
		}

		sidecarVolumeMounts = append(sidecarVolumeMounts, corev1.VolumeMount{
			Name:      volumeName,
			MountPath: mountPath,
		})
	}

	// Build sidecar environment variables
	var sidecarEnv []corev1.EnvVar
	sidecarEnv = append(sidecarEnv, corev1.EnvVar{
		Name:  "PORT",
		Value: "30090",
	})
	sidecarEnv = append(sidecarEnv, corev1.EnvVar{
		Name:  "LORA_DOWNLOAD_BASE_DIR",
		Value: mountPath + "/lora-adapters",
	})
	for _, envVar := range sidecarConfig.Env {
		sidecarEnv = append(sidecarEnv, corev1.EnvVar{
			Name:  envVar.Name,
			Value: envVar.Value,
		})
	}

	// Build sidecar resources
	sidecarResources := corev1.ResourceRequirements{
		Requests: corev1.ResourceList{},
		Limits:   corev1.ResourceList{},
	}

	if sidecarConfig.Resources.CPU != "" {
		sidecarResources.Requests[corev1.ResourceCPU] = resource.MustParse(
			sidecarConfig.Resources.CPU,
		)
		sidecarResources.Limits[corev1.ResourceCPU] = resource.MustParse(
			sidecarConfig.Resources.CPU,
		)
	} else {
		sidecarResources.Requests[corev1.ResourceCPU] = resource.MustParse("0.5")
		sidecarResources.Limits[corev1.ResourceCPU] = resource.MustParse("0.5")
	}

	if sidecarConfig.Resources.Memory != "" {
		sidecarResources.Requests[corev1.ResourceMemory] = resource.MustParse(
			sidecarConfig.Resources.Memory,
		)
		sidecarResources.Limits[corev1.ResourceMemory] = resource.MustParse(
			sidecarConfig.Resources.Memory,
		)
	} else {
		sidecarResources.Requests[corev1.ResourceMemory] = resource.MustParse("128Mi")
		sidecarResources.Limits[corev1.ResourceMemory] = resource.MustParse("128Mi")
	}

	if sidecarConfig.Resources.GPU != "" {
		gpuType := "nvidia.com/gpu"
		if sidecarConfig.Resources.GPUType != "" {
			gpuType = sidecarConfig.Resources.GPUType
		}
		gpuResource := resource.MustParse(sidecarConfig.Resources.GPU)
		sidecarResources.Requests[corev1.ResourceName(gpuType)] = gpuResource
		sidecarResources.Limits[corev1.ResourceName(gpuType)] = gpuResource
	} else {
		gpuType := "nvidia.com/gpu"
		if sidecarConfig.Resources.GPUType != "" {
			gpuType = sidecarConfig.Resources.GPUType
		}
		zeroQty := resource.MustParse("0")
		sidecarResources.Requests[corev1.ResourceName(gpuType)] = zeroQty
		sidecarResources.Limits[corev1.ResourceName(gpuType)] = zeroQty
	}

	// Get sidecar image
	sidecarImage := sidecarConfig.Image.Registry + "/" + sidecarConfig.Image.Name

	// Get sidecar image pull policy
	sidecarImagePullPolicy := corev1.PullIfNotPresent
	if sidecarConfig.Image.PullPolicy != "" {
		sidecarImagePullPolicy = corev1.PullPolicy(sidecarConfig.Image.PullPolicy)
	}

	// Build sidecar container
	sidecarContainer := corev1.Container{
		Name:            sidecarConfig.Name,
		Image:           sidecarImage,
		ImagePullPolicy: sidecarImagePullPolicy,
		Command:         sidecarConfig.Command,
		Args:            sidecarConfig.Args,
		Env:             sidecarEnv,
		Resources:       sidecarResources,
		VolumeMounts:    sidecarVolumeMounts,
	}

	return sidecarContainer
}

// deploymentNeedsUpdate checks if the deployment needs to be updated
func (r *VLLMRuntimeReconciler) deploymentNeedsUpdate(
	ctx context.Context,
	dep *appsv1.Deployment,
	vr *productionstackv1alpha1.VLLMRuntime,
) bool {

	log := log.FromContext(ctx)

	// Every comparison below reads the first container, and the port check
	// its first port. A live Deployment edited to drop either cannot be
	// compared, so rewrite it from the spec rather than index out of range.
	if len(dep.Spec.Template.Spec.Containers) == 0 ||
		len(dep.Spec.Template.Spec.Containers[0].Ports) == 0 {
		log.Info("Deployment has no vLLM container or port to compare; updating it")
		return true
	}

	// Generate the expected deployment
	expectedDep := r.deploymentForVLLMRuntime(vr)

	// Compare replicas
	if *dep.Spec.Replicas != vr.Spec.DeploymentConfig.Replicas {
		return true
	}

	// Compare model URL
	expectedModelURL := vr.Spec.Model.ModelURL
	actualModelURL := ""
	// For vllm serve, the model URL is the first argument after the command
	if len(dep.Spec.Template.Spec.Containers[0].Args) > 0 {
		actualModelURL = dep.Spec.Template.Spec.Containers[0].Args[0]
	}
	if expectedModelURL != actualModelURL {
		log.Info("Model URL mismatch", "expected", expectedModelURL, "actual", actualModelURL)
		return true
	}

	// Compare port
	expectedPort := vr.Spec.VLLMConfig.Port
	actualPort := dep.Spec.Template.Spec.Containers[0].Ports[0].ContainerPort
	if expectedPort != actualPort {
		log.Info("Port mismatch", "expected", expectedPort, "actual", actualPort)
		return true
	}

	// Compare image
	if expectedDep.Spec.Template.Spec.Containers[0].Image != dep.Spec.Template.Spec.Containers[0].Image {
		log.Info(
			"Image mismatch",
			"expected",
			expectedDep.Spec.Template.Spec.Containers[0].Image,
			"actual",
			dep.Spec.Template.Spec.Containers[0].Image,
		)
		return true
	}

	// Compare resources
	expectedResources := expectedDep.Spec.Template.Spec.Containers[0].Resources
	actualResources := dep.Spec.Template.Spec.Containers[0].Resources
	if !reflect.DeepEqual(expectedResources, actualResources) {
		log.Info("Resources mismatch", "expected", expectedResources, "actual", actualResources)
		return true
	}

	// Compare the rendered KV connector configuration. It carries the
	// connector, so it catches a mode switch; in Multiprocess mode it also
	// carries the cache server address and transfer mode. It is absent when
	// LMCache is disabled, so it also catches LMCache being turned on or off.
	expectedKVConfig := kvTransferConfigArg(expectedDep.Spec.Template.Spec.Containers[0].Args)
	actualKVConfig := kvTransferConfigArg(dep.Spec.Template.Spec.Containers[0].Args)
	if expectedKVConfig != actualKVConfig {
		log.Info(
			"KV transfer config mismatch",
			"expected", expectedKVConfig,
			"actual", actualKVConfig,
		)
		return true
	}

	// Compare the in-process LMCache settings, which are rendered as env vars
	// rather than args. Only in InProcess mode: in Multiprocess mode they are
	// not rendered, and comparing their API defaults against nothing would
	// report drift that no update can resolve, rolling the engine on every
	// reconcile.
	if vr.Spec.LMCacheConfig.Enabled && !isLMCacheMultiprocess(vr) {
		expectedEnv := lmcacheEnvValues(expectedDep.Spec.Template.Spec.Containers[0].Env)
		actualEnv := lmcacheEnvValues(dep.Spec.Template.Spec.Containers[0].Env)
		if !maps.Equal(expectedEnv, actualEnv) {
			log.Info(
				"In-process LMCache configuration mismatch",
				"expected", expectedEnv,
				"actual", actualEnv,
			)
			return true
		}
	}

	// Compare the whole affinity rather than dereferencing its node half:
	// a runtime without nodeSelectorTerms renders no affinity at all, so both
	// sides are nil. Semantic equality treats nil and empty lists as equal, as
	// the API server's round trip does.
	expectedAffinity := expectedDep.Spec.Template.Spec.Affinity
	actualAffinity := dep.Spec.Template.Spec.Affinity
	if !equality.Semantic.DeepEqual(expectedAffinity, actualAffinity) {
		log.Info(
			"Affinity mismatch",
			"expected",
			expectedAffinity,
			"actual",
			actualAffinity,
		)
		return true
	}

	// hostIPC decides whether the engine shares the host /dev/shm with a cache
	// server, so toggling it must roll the pods.
	expectedHostIPC := expectedDep.Spec.Template.Spec.HostIPC
	actualHostIPC := dep.Spec.Template.Spec.HostIPC
	if expectedHostIPC != actualHostIPC {
		log.Info(
			"HostIPC mismatch",
			"expected",
			expectedHostIPC,
			"actual",
			actualHostIPC,
		)
		return true
	}

	actualTolerations := dep.Spec.Template.Spec.Tolerations
	expectedTolerations := expectedDep.Spec.Template.Spec.Tolerations
	if !reflect.DeepEqual(expectedTolerations, actualTolerations) {
		log.Info(
			"Tolerations mismatch",
			"expected",
			expectedTolerations,
			"actual",
			actualTolerations,
		)
		return true
	}

	expectedRuntimeClass := expectedDep.Spec.Template.Spec.RuntimeClassName
	actualRuntimeClass := dep.Spec.Template.Spec.RuntimeClassName

	if !reflect.DeepEqual(expectedRuntimeClass, actualRuntimeClass) {
		log.Info(
			"RuntimeClass mismatch",
			"expected",
			expectedRuntimeClass,
			"actual",
			actualRuntimeClass,
		)
		return true
	}

	expectedPodAnnotations := expectedDep.Spec.Template.Annotations
	actualPodAnnotations := dep.Spec.Template.Annotations

	for k, v := range expectedPodAnnotations {
		if actualPodAnnotations[k] != v {
			log.Info(
				"Pod annotations mismatch",
				"key",
				k,
				"expected",
				v,
				"actual",
				actualPodAnnotations[k],
			)

			return true
		}
	}

	// Detect drift in the /dev/shm volume (driven by shmSize). We compare the
	// "dshm" volume/mount specifically instead of the whole Volumes slice,
	// whose server-side defaults (e.g. ConfigMap DefaultMode) would otherwise
	// cause a permanent mismatch and an endless reconcile loop.
	if !reflect.DeepEqual(
		findVolumeByName(expectedDep.Spec.Template.Spec.Volumes, "dshm"),
		findVolumeByName(dep.Spec.Template.Spec.Volumes, "dshm"),
	) {
		log.Info("shm volume mismatch")
		return true
	}

	if len(dep.Spec.Template.Spec.Containers) > 0 &&
		!reflect.DeepEqual(
			findVolumeMountByName(expectedDep.Spec.Template.Spec.Containers[0].VolumeMounts, "dshm"),
			findVolumeMountByName(dep.Spec.Template.Spec.Containers[0].VolumeMounts, "dshm"),
		) {
		log.Info("shm volume mount mismatch")
		return true
	}

	return false
}

// findVolumeByName returns a pointer to the named volume, or nil if absent.
func findVolumeByName(volumes []corev1.Volume, name string) *corev1.Volume {
	for i := range volumes {
		if volumes[i].Name == name {
			return &volumes[i]
		}
	}
	return nil
}

// findVolumeMountByName returns a pointer to the named volume mount, or nil.
func findVolumeMountByName(mounts []corev1.VolumeMount, name string) *corev1.VolumeMount {
	for i := range mounts {
		if mounts[i].Name == name {
			return &mounts[i]
		}
	}
	return nil
}

// updateStatus updates the status of the VLLMRuntime
func (r *VLLMRuntimeReconciler) updateStatus(
	ctx context.Context,
	vr *productionstackv1alpha1.VLLMRuntime,
	dep *appsv1.Deployment,
) error {
	return retry.RetryOnConflict(retry.DefaultRetry, func() error {
		// Get the latest version of the VLLMRuntime
		latestVR := &productionstackv1alpha1.VLLMRuntime{}
		if err := r.Get(ctx, types.NamespacedName{Name: vr.Name, Namespace: vr.Namespace}, latestVR); err != nil {
			return err
		}

		// Update the status fields
		latestVR.Status.LastUpdated = metav1.Now()

		// Update model status based on deployment status
		if dep.Status.AvailableReplicas == *dep.Spec.Replicas &&
			dep.Status.UnavailableReplicas == 0 {
			latestVR.Status.ModelStatus = "Ready"
		} else if dep.Status.UpdatedReplicas > 0 && dep.Status.AvailableReplicas != *dep.Spec.Replicas && dep.Status.UnavailableReplicas > 0 {
			// If we have updated replicas but they're not yet available, mark as updating
			latestVR.Status.ModelStatus = "Updating"
		} else if dep.Status.UnavailableReplicas > 0 {
			latestVR.Status.ModelStatus = "NotReady"
		} else {
			latestVR.Status.ModelStatus = "Unknown"
		}

		// Set replica count and selector for the scale subresource (required by HPA for AverageValue metrics)
		latestVR.Status.Replicas = dep.Status.Replicas
		latestVR.Status.Selector = metav1.FormatLabelSelector(dep.Spec.Selector)

		// Expose additional deployment status fields
		latestVR.Status.AvailableReplicas = dep.Status.AvailableReplicas
		latestVR.Status.UpdatedReplicas = dep.Status.UpdatedReplicas
		latestVR.Status.UnavailableReplicas = dep.Status.UnavailableReplicas

		return r.Status().Update(ctx, latestVR)
	})
}

// reconcileScaledObject creates or updates the KEDA ScaledObject for autoscaling
func (r *VLLMRuntimeReconciler) reconcileScaledObject(
	ctx context.Context,
	vllmRuntime *productionstackv1alpha1.VLLMRuntime,
) error {
	cfg := vllmRuntime.Spec.AutoscalingConfig
	jobName := vllmRuntime.Name

	scaledObject := &unstructured.Unstructured{}
	scaledObject.SetAPIVersion("keda.sh/v1alpha1")
	scaledObject.SetKind("ScaledObject")
	scaledObject.SetName(vllmRuntime.Name + "-scaledobject")
	scaledObject.SetNamespace(vllmRuntime.Namespace)
	scaledObject.SetOwnerReferences([]metav1.OwnerReference{
		*metav1.NewControllerRef(vllmRuntime, productionstackv1alpha1.GroupVersion.WithKind("VLLMRuntime")),
	})

	prometheusAddr := cfg.Triggers.PrometheusAddress
	servedModelName := vllmRuntime.Spec.Model.ModelURL
	// Check extraArgs for --served-model-name override
	for _, arg := range vllmRuntime.Spec.VLLMConfig.ExtraArgs {
		if strings.HasPrefix(arg, "--served-model-name=") {
			servedModelName = strings.TrimPrefix(arg, "--served-model-name=")
			break
		}
	}

	spec := map[string]interface{}{
		"scaleTargetRef": map[string]interface{}{
			"apiVersion": "production-stack.vllm.ai/v1alpha1",
			"kind":       "VLLMRuntime",
			"name":       vllmRuntime.Name,
		},
		"minReplicaCount": *cfg.MinReplicas,
		"maxReplicaCount": cfg.MaxReplicas,
		"pollingInterval": *cfg.PollingInterval,
		"cooldownPeriod":  *cfg.ScaleDownPolicy.ScaleToZeroDelaySeconds,
		"advanced": map[string]interface{}{
			"horizontalPodAutoscalerConfig": map[string]interface{}{
				"behavior": map[string]interface{}{
					"scaleUp": map[string]interface{}{
						"stabilizationWindowSeconds": *cfg.ScaleUpPolicy.StabilizationWindowSeconds,
						"policies": []map[string]interface{}{
							{
								"type":          "Pods",
								"value":         *cfg.ScaleUpPolicy.PodValue,
								"periodSeconds": *cfg.ScaleUpPolicy.PeriodSeconds,
							},
						},
					},
					"scaleDown": map[string]interface{}{
						"stabilizationWindowSeconds": *cfg.ScaleDownPolicy.StabilizationWindowSeconds,
						"policies": []map[string]interface{}{
							{
								"type":          "Pods",
								"value":         *cfg.ScaleDownPolicy.PodValue,
								"periodSeconds": *cfg.ScaleDownPolicy.PeriodSeconds,
							},
						},
					},
				},
			},
		},
		"triggers": []map[string]interface{}{
			{
				"type":       "prometheus",
				"metricType": "Value",
				"metadata": map[string]string{
					"serverAddress": prometheusAddr,
					"metricName":    "vllm_incoming_keepalive",
					"query": fmt.Sprintf(
						`sum(rate(vllm:num_incoming_requests_total{namespace="%s", model="%s"}[2m]) > bool 0)`,
						vllmRuntime.Namespace,
						servedModelName,
					),
					"threshold": "1",
				},
			},
			{
				"type": "prometheus",
				"metadata": map[string]string{
					"serverAddress": prometheusAddr,
					"metricName":    "vllm_requests_running",
					"query": fmt.Sprintf(
						`sum(vllm:num_requests_running{job="%s"})`,
						jobName,
					),
					"threshold": fmt.Sprintf("%d", *cfg.Triggers.RequestsRunningThreshold),
				},
			},
			{
				"type": "prometheus",
				"metadata": map[string]string{
					"serverAddress": prometheusAddr,
					"metricName":    "vllm_generation_tokens_rate",
					"query": fmt.Sprintf(
						`sum(rate(vllm:generation_tokens_total{job="%s"}[1m]))`,
						jobName,
					),
					"threshold": fmt.Sprintf("%d", *cfg.Triggers.GenerationTokensThreshold),
				},
			},
			{
				"type": "prometheus",
				"metadata": map[string]string{
					"serverAddress": prometheusAddr,
					"metricName":    "vllm_prompt_tokens_rate",
					"query": fmt.Sprintf(
						`sum(rate(vllm:prompt_tokens_total{job="%s"}[1m]))`,
						jobName,
					),
					"threshold": fmt.Sprintf("%d", *cfg.Triggers.PromptTokensThreshold),
				},
			},
		},
	}

	scaledObject.Object["spec"] = spec
	return r.Client.Patch(
		ctx,
		scaledObject,
		client.Apply,
		client.FieldOwner("vllmruntime-controller"),
	)
}

// serviceForVLLMRuntime returns a VLLMRuntime Service object
func (r *VLLMRuntimeReconciler) serviceForVLLMRuntime(
	vllmRuntime *productionstackv1alpha1.VLLMRuntime,
) *corev1.Service {
	labels := map[string]string{"app": vllmRuntime.Name}
	maps.Copy(labels, vllmRuntime.Labels)

	svc := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      vllmRuntime.Name,
			Namespace: vllmRuntime.Namespace,
		},
		Spec: corev1.ServiceSpec{
			Type:     corev1.ServiceTypeClusterIP,
			Selector: labels,
			Ports: []corev1.ServicePort{
				{
					Name:       "http",
					Port:       80,
					TargetPort: intstr.FromInt32(vllmRuntime.Spec.VLLMConfig.Port),
					Protocol:   corev1.ProtocolTCP,
				},
			},
		},
	}

	// Set the owner reference
	ctrl.SetControllerReference(vllmRuntime, svc, r.Scheme)
	return svc
}

// serviceNeedsUpdate checks if the service needs to be updated
func (r *VLLMRuntimeReconciler) serviceNeedsUpdate(
	svc *corev1.Service,
	vr *productionstackv1alpha1.VLLMRuntime,
) bool {
	// Compare target port
	expectedTargetPort := int(vr.Spec.VLLMConfig.Port)
	actualTargetPort := svc.Spec.Ports[0].TargetPort.IntValue()

	return expectedTargetPort != actualTargetPort
}

// pvcForVLLMRuntime returns a VLLMRuntime PVC object
func (r *VLLMRuntimeReconciler) pvcForVLLMRuntime(
	vllmRuntime *productionstackv1alpha1.VLLMRuntime,
) *corev1.PersistentVolumeClaim {
	labels := map[string]string{"app": vllmRuntime.Name}
	maps.Copy(labels, vllmRuntime.Labels)

	// Set default values if not specified
	accessMode := corev1.ReadWriteOnce
	if vllmRuntime.Spec.StorageConfig.AccessMode != "" {
		switch vllmRuntime.Spec.StorageConfig.AccessMode {
		case "ReadWriteOnce":
			accessMode = corev1.ReadWriteOnce
		case "ReadOnlyMany":
			accessMode = corev1.ReadOnlyMany
		case "ReadWriteMany":
			accessMode = corev1.ReadWriteMany
		}
	}

	size := "10Gi"
	if vllmRuntime.Spec.StorageConfig.Size != "" {
		size = vllmRuntime.Spec.StorageConfig.Size
	}

	pvc := &corev1.PersistentVolumeClaim{
		ObjectMeta: metav1.ObjectMeta{
			Name:      vllmRuntime.Name,
			Namespace: vllmRuntime.Namespace,
			Labels:    labels,
		},
		Spec: corev1.PersistentVolumeClaimSpec{
			AccessModes: []corev1.PersistentVolumeAccessMode{accessMode},
			Resources: corev1.VolumeResourceRequirements{
				Requests: corev1.ResourceList{
					corev1.ResourceStorage: resource.MustParse(size),
				},
			},
		},
	}

	// Add storage class if specified
	if vllmRuntime.Spec.StorageConfig.StorageClassName != "" {
		pvc.Spec.StorageClassName = &vllmRuntime.Spec.StorageConfig.StorageClassName
	}

	// Set the owner reference
	ctrl.SetControllerReference(vllmRuntime, pvc, r.Scheme)
	return pvc
}

// pvcNeedsUpdate checks if the PVC needs to be updated
func (r *VLLMRuntimeReconciler) pvcNeedsUpdate(
	pvc *corev1.PersistentVolumeClaim,
	vr *productionstackv1alpha1.VLLMRuntime,
) bool {
	// Compare storage size
	expectedSize := "10Gi"
	if vr.Spec.StorageConfig.Size != "" {
		expectedSize = vr.Spec.StorageConfig.Size
	}
	actualSize := pvc.Spec.Resources.Requests[corev1.ResourceStorage]

	return expectedSize != actualSize.String()
}

func (r *VLLMRuntimeReconciler) configMapForVLLMRuntime(
	vr *productionstackv1alpha1.VLLMRuntime,
) *corev1.ConfigMap {
	cm := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      vr.Name + "-chat-template",
			Namespace: vr.Namespace,
		},
		Data: map[string]string{
			"chatTemplate": vr.Spec.Model.ChatTemplate,
		},
	}

	ctrl.SetControllerReference(vr, cm, r.Scheme)
	return cm
}

func (r *VLLMRuntimeReconciler) configMapNeedsUpdate(
	cm *corev1.ConfigMap,
	vr *productionstackv1alpha1.VLLMRuntime,
) bool {
	actualData := cm.Data["chatTemplate"]
	currentData := vr.Spec.Model.ChatTemplate

	return actualData != currentData
}

// SetupWithManager sets up the controller with the Manager.
func (r *VLLMRuntimeReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&productionstackv1alpha1.VLLMRuntime{}).
		Owns(&appsv1.Deployment{}).
		Owns(&corev1.Service{}).
		Owns(&corev1.PersistentVolumeClaim{}).
		Owns(&corev1.ConfigMap{}).
		Complete(r)
}
