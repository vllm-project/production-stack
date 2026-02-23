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
	"fmt"
	"maps"
	"reflect"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
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
// +kubebuilder:rbac:groups=core,resources=secrets,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=services,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=persistentvolumeclaims,verbs=get;list;watch;create;update;patch;delete

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
func (r *VLLMRuntimeReconciler) Reconcile(
	ctx context.Context,
	req ctrl.Request,
) (ctrl.Result, error) {
	log := log.FromContext(ctx)
	log.Info("=== RECONCILE START ===", "Name", req.Name, "Namespace", req.Namespace)

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

	// Check if PD disaggregation is enabled
	log.Info("Checking PD disaggregation flag", "Name", vllmRuntime.Name, "EnablePDDisaggregation", vllmRuntime.Spec.EnablePDDisaggregation)
	if vllmRuntime.Spec.EnablePDDisaggregation {
		log.Info("Processing VLLMRuntime with PD disaggregation enabled", "Name", vllmRuntime.Name)
		return r.reconcilePDDisaggregation(ctx, vllmRuntime)
	}

	log.Info("Processing VLLMRuntime with legacy mode (single deployment)", "Name", vllmRuntime.Name)

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

	// Update the status
	if err := r.updateStatus(ctx, vllmRuntime, found); err != nil {
		log.Error(err, "Failed to update VLLMRuntime status")
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, nil
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

	if vllmRuntime.Spec.Model.MaxModelLen > 0 {
		args = append(
			args,
			"--max-model-len",
			fmt.Sprintf("%d", vllmRuntime.Spec.Model.MaxModelLen),
		)
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
			"--gpu_memory_utilization",
			vllmRuntime.Spec.VLLMConfig.GpuMemoryUtilization,
		)
	}

	if vllmRuntime.Spec.VLLMConfig.MaxLoras > 0 {
		args = append(args, "--max_loras", fmt.Sprintf("%d", vllmRuntime.Spec.VLLMConfig.MaxLoras))
	}

	if vllmRuntime.Spec.VLLMConfig.ExtraArgs != nil {
		args = append(args, vllmRuntime.Spec.VLLMConfig.ExtraArgs...)
	}

	if vllmRuntime.Spec.Model.ChatTemplate != "" {
		args = append(args, "--chat-template", "/etc/chat-template.json")
	}

	// Build environment variables
	env := []corev1.EnvVar{}
	// Only set VLLM_USE_V1 when explicitly set to false
	// When using LMCacheConnectorV1, don't set VLLM_USE_V1 to avoid compatibility issues
	if !vllmRuntime.Spec.VLLMConfig.V1 {
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
			corev1.EnvVar{
				Name:  "LMCACHE_USE_EXPERIMENTAL",
				Value: "True",
			},
			corev1.EnvVar{
				Name:  "VLLM_RPC_TIMEOUT",
				Value: "1000000",
			},
		)

		// Add KV transfer config based on V1 flag
		var lmcache_config string
		if vllmRuntime.Spec.VLLMConfig.V1 {
			// For V1, include kv_connector_extra_config
			lmcache_config = `{"kv_connector":"LMCacheConnectorV1","kv_role":"kv_both","kv_connector_extra_config":{"discard_partial_chunks":false}}`
		} else {
			lmcache_config = `{"kv_connector":"LMCacheConnector","kv_role":"kv_both"}`
		}
		args = append(args, "--kv-transfer-config", lmcache_config)

		if vllmRuntime.Spec.LMCacheConfig.CPUOffloadingBufferSize != "" {
			env = append(env,
				corev1.EnvVar{
					Name:  "LMCACHE_LOCAL_CPU",
					Value: "True",
				},
				corev1.EnvVar{
					Name:  "LMCACHE_MAX_LOCAL_CPU_SIZE",
					Value: vllmRuntime.Spec.LMCacheConfig.CPUOffloadingBufferSize,
				},
			)
		}

		if vllmRuntime.Spec.LMCacheConfig.DiskOffloadingBufferSize != "" {
			env = append(env,
				corev1.EnvVar{
					Name:  "LMCACHE_LOCAL_DISK",
					Value: "True",
				},
				corev1.EnvVar{
					Name:  "LMCACHE_MAX_LOCAL_DISK_SIZE",
					Value: vllmRuntime.Spec.LMCacheConfig.DiskOffloadingBufferSize,
				},
			)
		}

		if vllmRuntime.Spec.LMCacheConfig.RemoteURL != "" {
			env = append(env,
				corev1.EnvVar{
					Name:  "LMCACHE_REMOTE_URL",
					Value: vllmRuntime.Spec.LMCacheConfig.RemoteURL,
				},
				corev1.EnvVar{
					Name:  "LMCACHE_REMOTE_SERDE",
					Value: vllmRuntime.Spec.LMCacheConfig.RemoteSerde,
				},
			)
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
			Labels:    labels,
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
					Labels: labels,
				},
				Spec: corev1.PodSpec{
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

	// Compare LM Cache configuration
	expectedLMCacheConfig := vr.Spec.LMCacheConfig
	actualLMCacheConfig := dep.Spec.Template.Spec.Containers[0].Env

	// Extract actual values from environment variables
	actualEnabled := false
	actualCPUOffloadingBufferSize := ""
	actualDiskOffloadingBufferSize := ""
	actualRemoteURL := ""
	actualRemoteSerde := ""

	for _, env := range actualLMCacheConfig {
		switch env.Name {
		case "LMCACHE_USE_EXPERIMENTAL":
			actualEnabled = env.Value == "True"
		case "LMCACHE_MAX_LOCAL_CPU_SIZE":
			actualCPUOffloadingBufferSize = env.Value
		case "LMCACHE_MAX_LOCAL_DISK_SIZE":
			actualDiskOffloadingBufferSize = env.Value
		case "LMCACHE_REMOTE_URL":
			actualRemoteURL = env.Value
		case "LMCACHE_REMOTE_SERDE":
			actualRemoteSerde = env.Value
		}
	}

	// Compare specific fields
	if expectedLMCacheConfig.Enabled != actualEnabled ||
		expectedLMCacheConfig.CPUOffloadingBufferSize != actualCPUOffloadingBufferSize ||
		expectedLMCacheConfig.DiskOffloadingBufferSize != actualDiskOffloadingBufferSize ||
		expectedLMCacheConfig.RemoteURL != actualRemoteURL ||
		expectedLMCacheConfig.RemoteSerde != actualRemoteSerde {
		log.Info(
			"LM Cache configuration mismatch",
			"expected",
			expectedLMCacheConfig,
			"actual",
			actualLMCacheConfig,
		)
		return true
	}

	actualAdditionalArgs := dep.Spec.Template.Spec.Affinity.NodeAffinity
	expectedAdditionalArgs := expectedDep.Spec.Template.Spec.Affinity.NodeAffinity
	if !reflect.DeepEqual(expectedAdditionalArgs, actualAdditionalArgs) {
		log.Info(
			"Node affinity mismatch",
			"expected",
			expectedAdditionalArgs,
			"actual",
			actualAdditionalArgs,
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

	return false
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

		return r.Status().Update(ctx, latestVR)
	})
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
	// For PD disaggregation mode, we don't update the legacy service
	// The prefill/decode services are handled separately
	if vr.Spec.EnablePDDisaggregation {
		return false
	}

	// Compare target port for legacy mode
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

// reconcilePDDisaggregation handles VLLMRuntime resources with PD disaggregation enabled
func (r *VLLMRuntimeReconciler) reconcilePDDisaggregation(ctx context.Context, vllmRuntime *productionstackv1alpha1.VLLMRuntime) (ctrl.Result, error) {
	log := log.FromContext(ctx)

	if vllmRuntime.Spec.Topology == nil {
		return ctrl.Result{}, fmt.Errorf("topology configuration is required when EnablePDDisaggregation=true")
	}

	// Handle Prefill resources
	if err := r.reconcilePrefillResources(ctx, vllmRuntime); err != nil {
		log.Error(err, "Failed to reconcile prefill resources")
		return ctrl.Result{}, err
	}

	// Handle Decode resources
	if err := r.reconcileDecodeResources(ctx, vllmRuntime); err != nil {
		log.Error(err, "Failed to reconcile decode resources")
		return ctrl.Result{}, err
	}

	// Update the status
	if err := r.updatePDStatus(ctx, vllmRuntime); err != nil {
		log.Error(err, "Failed to update VLLMRuntime status")
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, nil
}

// reconcilePrefillResources handles all prefill-related resources
func (r *VLLMRuntimeReconciler) reconcilePrefillResources(ctx context.Context, vllmRuntime *productionstackv1alpha1.VLLMRuntime) error {
	log := log.FromContext(ctx)

	// Service for prefill
	serviceName := fmt.Sprintf("%s-prefill", vllmRuntime.Name)
	foundService := &corev1.Service{}
	err := r.Get(ctx, types.NamespacedName{Name: serviceName, Namespace: vllmRuntime.Namespace}, foundService)
	if err != nil && errors.IsNotFound(err) {
		// Define a new service
		svc := r.serviceForNode(vllmRuntime, &vllmRuntime.Spec.Topology.Prefill, "prefill")
		log.Info("Creating a new Service", "Service.Namespace", svc.Namespace, "Service.Name", svc.Name)
		err = r.Create(ctx, svc)
		if err != nil {
			log.Error(err, "Failed to create new Service", "Service.Namespace", svc.Namespace, "Service.Name", svc.Name)
			return err
		}
	} else if err != nil {
		return err
	}

	// PVC for prefill (if storage is enabled)
	if vllmRuntime.Spec.Topology.Prefill.StorageConfig.Enabled {
		pvcName := fmt.Sprintf("%s-prefill", vllmRuntime.Name)
		foundPVC := &corev1.PersistentVolumeClaim{}
		err = r.Get(ctx, types.NamespacedName{Name: pvcName, Namespace: vllmRuntime.Namespace}, foundPVC)
		if err != nil && errors.IsNotFound(err) {
			// Define a new PVC
			pvc := r.pvcForNode(vllmRuntime, &vllmRuntime.Spec.Topology.Prefill, "prefill")
			log.Info("Creating a new PVC", "PVC.Namespace", pvc.Namespace, "PVC.Name", pvc.Name)
			err = r.Create(ctx, pvc)
			if err != nil {
				log.Error(err, "Failed to create new PVC", "PVC.Namespace", pvc.Namespace, "PVC.Name", pvc.Name)
				return err
			}
		} else if err != nil {
			return err
		}
	}

	// Deployment for prefill
	deploymentName := fmt.Sprintf("%s-prefill", vllmRuntime.Name)
	found := &appsv1.Deployment{}
	err = r.Get(ctx, types.NamespacedName{Name: deploymentName, Namespace: vllmRuntime.Namespace}, found)
	if err != nil && errors.IsNotFound(err) {
		// Define a new deployment
		dep := r.deploymentForNode(vllmRuntime, &vllmRuntime.Spec.Topology.Prefill, "prefill")
		log.Info("Creating a new Deployment", "Deployment.Namespace", dep.Namespace, "Deployment.Name", dep.Name)
		err = r.Create(ctx, dep)
		if err != nil {
			log.Error(err, "Failed to create new Deployment", "Deployment.Namespace", dep.Namespace, "Deployment.Name", dep.Name)
			return err
		}
	} else if err != nil {
		return err
	}

	return nil
}

// reconcileDecodeResources handles all decode-related resources
func (r *VLLMRuntimeReconciler) reconcileDecodeResources(ctx context.Context, vllmRuntime *productionstackv1alpha1.VLLMRuntime) error {
	log := log.FromContext(ctx)

	// Service for decode
	serviceName := fmt.Sprintf("%s-decode", vllmRuntime.Name)
	foundService := &corev1.Service{}
	err := r.Get(ctx, types.NamespacedName{Name: serviceName, Namespace: vllmRuntime.Namespace}, foundService)
	if err != nil && errors.IsNotFound(err) {
		// Define a new service
		svc := r.serviceForNode(vllmRuntime, &vllmRuntime.Spec.Topology.Decode, "decode")
		log.Info("Creating a new Service", "Service.Namespace", svc.Namespace, "Service.Name", svc.Name)
		err = r.Create(ctx, svc)
		if err != nil {
			log.Error(err, "Failed to create new Service", "Service.Namespace", svc.Namespace, "Service.Name", svc.Name)
			return err
		}
	} else if err != nil {
		return err
	}

	// PVC for decode (if storage is enabled)
	if vllmRuntime.Spec.Topology.Decode.StorageConfig.Enabled {
		pvcName := fmt.Sprintf("%s-decode", vllmRuntime.Name)
		foundPVC := &corev1.PersistentVolumeClaim{}
		err = r.Get(ctx, types.NamespacedName{Name: pvcName, Namespace: vllmRuntime.Namespace}, foundPVC)
		if err != nil && errors.IsNotFound(err) {
			// Define a new PVC
			pvc := r.pvcForNode(vllmRuntime, &vllmRuntime.Spec.Topology.Decode, "decode")
			log.Info("Creating a new PVC", "PVC.Namespace", pvc.Namespace, "PVC.Name", pvc.Name)
			err = r.Create(ctx, pvc)
			if err != nil {
				log.Error(err, "Failed to create new PVC", "PVC.Namespace", pvc.Namespace, "PVC.Name", pvc.Name)
				return err
			}
		} else if err != nil {
			return err
		}
	}

	// Deployment for decode
	deploymentName := fmt.Sprintf("%s-decode", vllmRuntime.Name)
	found := &appsv1.Deployment{}
	err = r.Get(ctx, types.NamespacedName{Name: deploymentName, Namespace: vllmRuntime.Namespace}, found)
	if err != nil && errors.IsNotFound(err) {
		// Define a new deployment
		dep := r.deploymentForNode(vllmRuntime, &vllmRuntime.Spec.Topology.Decode, "decode")
		log.Info("Creating a new Deployment", "Deployment.Namespace", dep.Namespace, "Deployment.Name", dep.Name)
		err = r.Create(ctx, dep)
		if err != nil {
			log.Error(err, "Failed to create new Deployment", "Deployment.Namespace", dep.Namespace, "Deployment.Name", dep.Name)
			return err
		}
	} else if err != nil {
		return err
	}

	return nil
}

// serviceForNode returns a Service object for a specific node
func (r *VLLMRuntimeReconciler) serviceForNode(vllmRuntime *productionstackv1alpha1.VLLMRuntime, nodeConfig *productionstackv1alpha1.NodeConfig, nodeType string) *corev1.Service {
	labels := map[string]string{
		"app":       vllmRuntime.Name,
		"node-type": nodeType,
	}
	for k, v := range vllmRuntime.Labels {
		labels[k] = v
	}

	// For PD disaggregation, override the model label with node type
	// This allows VLLMRouter to identify prefill vs decode nodes
	if vllmRuntime.Spec.EnablePDDisaggregation {
		labels["model"] = fmt.Sprintf("%s-%s", labels["model"], nodeType)
	}

	serviceName := fmt.Sprintf("%s-%s", vllmRuntime.Name, nodeType)

	svc := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      serviceName,
			Namespace: vllmRuntime.Namespace,
		},
		Spec: corev1.ServiceSpec{
			Type:     corev1.ServiceTypeClusterIP,
			Selector: labels,
			Ports: []corev1.ServicePort{
				{
					Name:       "http",
					Port:       80,
					TargetPort: intstr.FromInt32(nodeConfig.VLLMConfig.Port),
					Protocol:   corev1.ProtocolTCP,
				},
			},
		},
	}

	// Set the owner reference
	ctrl.SetControllerReference(vllmRuntime, svc, r.Scheme)
	return svc
}

// pvcForNode returns a PVC object for a specific node
func (r *VLLMRuntimeReconciler) pvcForNode(vllmRuntime *productionstackv1alpha1.VLLMRuntime, nodeConfig *productionstackv1alpha1.NodeConfig, nodeType string) *corev1.PersistentVolumeClaim {
	labels := map[string]string{
		"app":       vllmRuntime.Name,
		"node-type": nodeType,
	}
	for k, v := range vllmRuntime.Labels {
		labels[k] = v
	}

	// For PD disaggregation, override the model label with node type
	// This allows VLLMRouter to identify prefill vs decode nodes
	if vllmRuntime.Spec.EnablePDDisaggregation {
		labels["model"] = fmt.Sprintf("%s-%s", labels["model"], nodeType)
	}

	pvcName := fmt.Sprintf("%s-%s", vllmRuntime.Name, nodeType)

	// Set default values if not specified
	accessMode := corev1.ReadWriteOnce
	if nodeConfig.StorageConfig.AccessMode != "" {
		switch nodeConfig.StorageConfig.AccessMode {
		case "ReadWriteOnce":
			accessMode = corev1.ReadWriteOnce
		case "ReadOnlyMany":
			accessMode = corev1.ReadOnlyMany
		case "ReadWriteMany":
			accessMode = corev1.ReadWriteMany
		}
	}

	size := "10Gi"
	if nodeConfig.StorageConfig.Size != "" {
		size = nodeConfig.StorageConfig.Size
	}

	pvc := &corev1.PersistentVolumeClaim{
		ObjectMeta: metav1.ObjectMeta{
			Name:      pvcName,
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
	if nodeConfig.StorageConfig.StorageClassName != "" {
		pvc.Spec.StorageClassName = &nodeConfig.StorageConfig.StorageClassName
	}

	// Set the owner reference
	ctrl.SetControllerReference(vllmRuntime, pvc, r.Scheme)
	return pvc
}

// deploymentForNode returns a Deployment object for a specific node (prefill or decode)
func (r *VLLMRuntimeReconciler) deploymentForNode(vllmRuntime *productionstackv1alpha1.VLLMRuntime, nodeConfig *productionstackv1alpha1.NodeConfig, nodeType string) *appsv1.Deployment {
	labels := map[string]string{
		"app":       vllmRuntime.Name,
		"node-type": nodeType,
	}
	for k, v := range vllmRuntime.Labels {
		labels[k] = v
	}

	// For PD disaggregation, override the model label with node type
	// This allows VLLMRouter to identify prefill vs decode nodes
	if vllmRuntime.Spec.EnablePDDisaggregation {
		labels["model"] = fmt.Sprintf("%s-%s", labels["model"], nodeType)
	}

	deploymentName := fmt.Sprintf("%s-%s", vllmRuntime.Name, nodeType)

	// Define probes
	readinessProbe := &corev1.Probe{
		ProbeHandler: corev1.ProbeHandler{
			HTTPGet: &corev1.HTTPGetAction{
				Path:   "/health",
				Port:   intstr.FromInt(int(nodeConfig.VLLMConfig.Port)),
				Scheme: corev1.URISchemeHTTP,
			},
		},
		InitialDelaySeconds: 30,
		PeriodSeconds:       20,
		TimeoutSeconds:      5,
		SuccessThreshold:    1,
		FailureThreshold:    10,
	}

	livenessProbe := &corev1.Probe{
		ProbeHandler: corev1.ProbeHandler{
			HTTPGet: &corev1.HTTPGetAction{
				Path:   "/health",
				Port:   intstr.FromInt(int(nodeConfig.VLLMConfig.Port)),
				Scheme: corev1.URISchemeHTTP,
			},
		},
		InitialDelaySeconds: 300,
		PeriodSeconds:       20,
		TimeoutSeconds:      3,
		SuccessThreshold:    1,
		FailureThreshold:    10,
	}

	// Build command line arguments
	args := r.buildVLLMArgsForNode(nodeConfig, nodeType)

	// Build environment variables
	env := r.buildEnvironmentVariablesForNode(nodeConfig, nodeType)

	// Add HF token if configured
	if nodeConfig.Model.HFTokenSecret.HFTokenSecretName != "" {
		tokenKey := nodeConfig.Model.HFTokenSecret.HFTokenKeyName
		if tokenKey == "" {
			tokenKey = "token"
		}
		env = append(env, corev1.EnvVar{
			Name: "HF_TOKEN",
			ValueFrom: &corev1.EnvVarSource{
				SecretKeyRef: &corev1.SecretKeySelector{
					LocalObjectReference: corev1.LocalObjectReference{
						Name: nodeConfig.Model.HFTokenSecret.HFTokenSecretName,
					},
					Key: tokenKey,
				},
			},
		})
	}

	// Build resource requirements
	resources := r.buildResourceRequirementsForNode(nodeConfig.DeploymentConfig.Resources)

	// Get the image
	image := nodeConfig.DeploymentConfig.Image.Registry + "/" + nodeConfig.DeploymentConfig.Image.Name

	// Get the image pull policy
	imagePullPolicy := corev1.PullIfNotPresent
	if nodeConfig.DeploymentConfig.Image.PullPolicy != "" {
		imagePullPolicy = corev1.PullPolicy(nodeConfig.DeploymentConfig.Image.PullPolicy)
	}

	// Build image pull secrets
	var imagePullSecrets []corev1.LocalObjectReference
	if nodeConfig.DeploymentConfig.Image.PullSecretName != "" {
		imagePullSecrets = append(imagePullSecrets, corev1.LocalObjectReference{
			Name: nodeConfig.DeploymentConfig.Image.PullSecretName,
		})
	}

	// Build volumes and volume mounts
	volumes, volumeMounts := r.buildVolumesAndMountsForNode(vllmRuntime, nodeConfig, nodeType)

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
					ContainerPort: nodeConfig.VLLMConfig.Port,
				},
			},
			Resources:      resources,
			VolumeMounts:   volumeMounts,
			ReadinessProbe: readinessProbe,
			LivenessProbe:  livenessProbe,
		},
	}

	if nodeConfig.DeploymentConfig.SidecarConfig.Enabled {
		containers = append(containers, r.buildSidecarContainerForNode(nodeConfig, volumeMounts))
	}

	dep := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      deploymentName,
			Namespace: vllmRuntime.Namespace,
			Labels:    labels,
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &nodeConfig.DeploymentConfig.Replicas,
			Strategy: appsv1.DeploymentStrategy{
				Type: appsv1.DeploymentStrategyType(nodeConfig.DeploymentConfig.DeployStrategy),
			},
			Selector: &metav1.LabelSelector{
				MatchLabels: labels,
			},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
				},
				Spec: corev1.PodSpec{
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

// updatePDStatus updates the status of the VLLMRuntime for PD disaggregation mode
func (r *VLLMRuntimeReconciler) updatePDStatus(ctx context.Context, vr *productionstackv1alpha1.VLLMRuntime) error {
	return retry.RetryOnConflict(retry.DefaultRetry, func() error {
		// Get the latest version of the VLLMRuntime
		latestVR := &productionstackv1alpha1.VLLMRuntime{}
		if err := r.Get(ctx, types.NamespacedName{Name: vr.Name, Namespace: vr.Namespace}, latestVR); err != nil {
			return err
		}

		// Update the status fields
		latestVR.Status.LastUpdated = metav1.Now()

		// Check both prefill and decode deployments
		prefillDeployment := &appsv1.Deployment{}
		decodeDeployment := &appsv1.Deployment{}

		prefillErr := r.Get(ctx, types.NamespacedName{Name: fmt.Sprintf("%s-prefill", vr.Name), Namespace: vr.Namespace}, prefillDeployment)
		decodeErr := r.Get(ctx, types.NamespacedName{Name: fmt.Sprintf("%s-decode", vr.Name), Namespace: vr.Namespace}, decodeDeployment)

		// Update model status based on both deployments
		if prefillErr == nil && decodeErr == nil {
			prefillReady := prefillDeployment.Status.AvailableReplicas == *prefillDeployment.Spec.Replicas
			decodeReady := decodeDeployment.Status.AvailableReplicas == *decodeDeployment.Spec.Replicas

			if prefillReady && decodeReady {
				latestVR.Status.ModelStatus = "Ready"
			} else if prefillDeployment.Status.UpdatedReplicas > 0 || decodeDeployment.Status.UpdatedReplicas > 0 {
				latestVR.Status.ModelStatus = "Updating"
			} else {
				latestVR.Status.ModelStatus = "NotReady"
			}
		} else {
			latestVR.Status.ModelStatus = "Unknown"
		}

		return r.Status().Update(ctx, latestVR)
	})
}

// buildVLLMArgsForNode builds the command line arguments for vLLM for a specific node
func (r *VLLMRuntimeReconciler) buildVLLMArgsForNode(nodeConfig *productionstackv1alpha1.NodeConfig, nodeType string) []string {
	args := []string{
		nodeConfig.Model.ModelURL,
		"--host", "0.0.0.0",
		"--port", fmt.Sprintf("%d", nodeConfig.VLLMConfig.Port),
	}

	if nodeConfig.Model.EnableLoRA {
		args = append(args, "--enable-lora")
	}

	if nodeConfig.Model.EnableTool {
		args = append(args, "--enable-auto-tool-choice")
	}

	if nodeConfig.Model.ToolCallParser != "" {
		args = append(args, "--tool-call-parser", nodeConfig.Model.ToolCallParser)
	}

	if nodeConfig.VLLMConfig.EnableChunkedPrefill {
		args = append(args, "--enable-chunked-prefill")
	} else {
		args = append(args, "--no-enable-chunked-prefill")
	}

	if nodeConfig.VLLMConfig.EnablePrefixCaching {
		args = append(args, "--enable-prefix-caching")
	} else {
		args = append(args, "--no-enable-prefix-caching")
	}

	if nodeConfig.Model.MaxModelLen > 0 {
		args = append(args, "--max-model-len", fmt.Sprintf("%d", nodeConfig.Model.MaxModelLen))
	}

	if nodeConfig.Model.DType != "" {
		args = append(args, "--dtype", nodeConfig.Model.DType)
	}

	if nodeConfig.VLLMConfig.TensorParallelSize > 0 {
		args = append(args, "--tensor-parallel-size", fmt.Sprintf("%d", nodeConfig.VLLMConfig.TensorParallelSize))
	}

	if nodeConfig.Model.MaxNumSeqs > 0 {
		args = append(args, "--max-num-seqs", fmt.Sprintf("%d", nodeConfig.Model.MaxNumSeqs))
	}

	if nodeConfig.VLLMConfig.GpuMemoryUtilization != "" {
		args = append(args, "--gpu_memory_utilization", nodeConfig.VLLMConfig.GpuMemoryUtilization)
	}

	if nodeConfig.VLLMConfig.MaxLoras > 0 {
		args = append(args, "--max_loras", fmt.Sprintf("%d", nodeConfig.VLLMConfig.MaxLoras))
	}

	// Add KV transfer config for PD disaggregation
	if nodeConfig.LMCacheConfig.Enabled {
		var kvRole string
		if nodeType == "prefill" {
			kvRole = "kv_producer"
		} else {
			kvRole = nodeConfig.LMCacheConfig.KVRole
			if kvRole == "" {
				kvRole = "kv_consumer" // default for decode
			}
		}

		var lmcache_config string
		if nodeConfig.VLLMConfig.V1 {
			// For V1, include kv_connector_extra_config based on node type
			if nodeType == "prefill" {
				rpcPort := nodeConfig.LMCacheConfig.RPCPort
				if rpcPort == "" {
					rpcPort = "producer1"
				}
				lmcache_config = fmt.Sprintf(`{"kv_connector":"LMCacheConnectorV1","kv_role":"%s","kv_connector_extra_config":{"discard_partial_chunks":false,"lmcache_rpc_port":"%s"}}`, kvRole, rpcPort)
			} else {
				// decode node
				rpcPort := nodeConfig.LMCacheConfig.RPCPort
				if rpcPort == "" {
					rpcPort = "consumer1"
				}
				skipTokens := nodeConfig.LMCacheConfig.SkipLastNTokens
				if skipTokens == 0 {
					skipTokens = 1
				}
				lmcache_config = fmt.Sprintf(`{"kv_connector":"LMCacheConnectorV1","kv_role":"%s","kv_connector_extra_config":{"discard_partial_chunks":false,"lmcache_rpc_port":"%s","skip_last_n_tokens":%d}}`, kvRole, rpcPort, skipTokens)
			}
		} else {
			lmcache_config = fmt.Sprintf(`{"kv_connector":"LMCacheConnector","kv_role":"%s"}`, kvRole)
		}
		args = append(args, "--kv-transfer-config", lmcache_config)
	}

	if nodeConfig.VLLMConfig.ExtraArgs != nil {
		args = append(args, nodeConfig.VLLMConfig.ExtraArgs...)
	}

	return args
}

// buildEnvironmentVariablesForNode builds the environment variables for the container for a specific node
func (r *VLLMRuntimeReconciler) buildEnvironmentVariablesForNode(nodeConfig *productionstackv1alpha1.NodeConfig, nodeType string) []corev1.EnvVar {
	env := []corev1.EnvVar{}

	// Only set VLLM_USE_V1 when explicitly set to false
	// When using LMCacheConnectorV1, don't set VLLM_USE_V1 to avoid compatibility issues
	if !nodeConfig.VLLMConfig.V1 {
		env = append(env, corev1.EnvVar{Name: "VLLM_USE_V1", Value: "0"})
	}

	if nodeConfig.Model.EnableLoRA {
		env = append(env, corev1.EnvVar{Name: "VLLM_ALLOW_RUNTIME_LORA_UPDATING", Value: "True"})
	}

	// LM Cache configuration
	if nodeConfig.LMCacheConfig.Enabled {
		env = append(env,
			corev1.EnvVar{Name: "LMCACHE_LOG_LEVEL", Value: "INFO"},
			corev1.EnvVar{Name: "LMCACHE_USE_EXPERIMENTAL", Value: "True"},
			corev1.EnvVar{Name: "VLLM_RPC_TIMEOUT", Value: "1000000"},
		)

		// Set KV role based on node type and configuration
		var kvRole string
		if nodeType == "prefill" {
			kvRole = "kv_producer"
		} else if nodeConfig.LMCacheConfig.KVRole != "" {
			kvRole = nodeConfig.LMCacheConfig.KVRole
		} else {
			kvRole = "kv_consumer" // default for decode
		}
		env = append(env, corev1.EnvVar{Name: "LMCACHE_KV_ROLE", Value: kvRole})

		if nodeConfig.LMCacheConfig.LocalCPU != "" || nodeConfig.LMCacheConfig.CPUOffloadingBufferSize != "" {
			env = append(env, corev1.EnvVar{Name: "LMCACHE_LOCAL_CPU", Value: "True"})
			cpuSize := nodeConfig.LMCacheConfig.LocalCPU
			if cpuSize == "" {
				cpuSize = nodeConfig.LMCacheConfig.CPUOffloadingBufferSize
			}
			if cpuSize != "" {
				env = append(env, corev1.EnvVar{Name: "LMCACHE_MAX_LOCAL_CPU_SIZE", Value: cpuSize})
			}
		} else {
			env = append(env, corev1.EnvVar{Name: "LMCACHE_LOCAL_CPU", Value: "False"})
		}

		if nodeConfig.LMCacheConfig.MaxLocalCPUSize > 0 {
			env = append(env, corev1.EnvVar{Name: "LMCACHE_MAX_LOCAL_CPU_SIZE", Value: fmt.Sprintf("%d", nodeConfig.LMCacheConfig.MaxLocalCPUSize)})
		}

	// Only set LMCACHE_LOCAL_DISK if Nixl is not enabled
	// Nixl requires local_disk to be None (unset), not False
	if !nodeConfig.LMCacheConfig.EnableNixl {
		if nodeConfig.LMCacheConfig.DiskOffloadingBufferSize != "" {
			env = append(env,
				corev1.EnvVar{Name: "LMCACHE_LOCAL_DISK", Value: "True"},
				corev1.EnvVar{Name: "LMCACHE_MAX_LOCAL_DISK_SIZE", Value: nodeConfig.LMCacheConfig.DiskOffloadingBufferSize},
			)
		} else {
			env = append(env, corev1.EnvVar{Name: "LMCACHE_LOCAL_DISK", Value: "False"})
		}
	}

		if nodeConfig.LMCacheConfig.RemoteURL != "" {
			env = append(env,
				corev1.EnvVar{Name: "LMCACHE_REMOTE_URL", Value: nodeConfig.LMCacheConfig.RemoteURL},
				corev1.EnvVar{Name: "LMCACHE_REMOTE_SERDE", Value: nodeConfig.LMCacheConfig.RemoteSerde},
			)
		}

		// Nixl/PD configuration
		// Note: LMCache 0.3.8+ uses LMCACHE_ENABLE_PD and LMCACHE_PD_* variables
		// We set both old (NIXL) and new (PD) names for compatibility
		if nodeConfig.LMCacheConfig.EnableNixl {
			// Enable PD disaggregation (new naming)
			env = append(env, corev1.EnvVar{Name: "LMCACHE_ENABLE_PD", Value: "True"})
			// Also set old naming for backward compatibility
			env = append(env, corev1.EnvVar{Name: "LMCACHE_ENABLE_NIXL", Value: "True"})

			// Set transfer channel to nixl (required in LMCache 0.3.8+)
			env = append(env, corev1.EnvVar{Name: "LMCACHE_TRANSFER_CHANNEL", Value: "nixl"})
			env = append(env, corev1.EnvVar{Name: "LMCACHE_PD_TRANSFER_CHANNEL", Value: "nixl"})

			if nodeConfig.LMCacheConfig.NixlRole != "" {
				// New naming: pd_role
				env = append(env, corev1.EnvVar{Name: "LMCACHE_PD_ROLE", Value: nodeConfig.LMCacheConfig.NixlRole})
				// Old naming
				env = append(env, corev1.EnvVar{Name: "LMCACHE_NIXL_ROLE", Value: nodeConfig.LMCacheConfig.NixlRole})
			}

			if nodeConfig.LMCacheConfig.NixlBufferSize != "" {
				// New naming: pd_buffer_size
				env = append(env, corev1.EnvVar{Name: "LMCACHE_PD_BUFFER_SIZE", Value: nodeConfig.LMCacheConfig.NixlBufferSize})
				env = append(env, corev1.EnvVar{Name: "LMCACHE_NIXL_BUFFER_SIZE", Value: nodeConfig.LMCacheConfig.NixlBufferSize})
			}

			if nodeConfig.LMCacheConfig.NixlBufferDevice != "" {
				// New naming: pd_buffer_device
				env = append(env, corev1.EnvVar{Name: "LMCACHE_PD_BUFFER_DEVICE", Value: nodeConfig.LMCacheConfig.NixlBufferDevice})
				env = append(env, corev1.EnvVar{Name: "LMCACHE_NIXL_BUFFER_DEVICE", Value: nodeConfig.LMCacheConfig.NixlBufferDevice})
			}

			// Prefill-specific Nixl config
			if nodeType == "prefill" {
				if nodeConfig.LMCacheConfig.NixlProxyHost != "" {
					// New naming: pd_proxy_host
					env = append(env, corev1.EnvVar{Name: "LMCACHE_PD_PROXY_HOST", Value: nodeConfig.LMCacheConfig.NixlProxyHost})
					env = append(env, corev1.EnvVar{Name: "LMCACHE_NIXL_PROXY_HOST", Value: nodeConfig.LMCacheConfig.NixlProxyHost})
				}
				if nodeConfig.LMCacheConfig.NixlProxyPort != "" {
					// New naming: pd_proxy_port
					env = append(env, corev1.EnvVar{Name: "LMCACHE_PD_PROXY_PORT", Value: nodeConfig.LMCacheConfig.NixlProxyPort})
					env = append(env, corev1.EnvVar{Name: "LMCACHE_NIXL_PROXY_PORT", Value: nodeConfig.LMCacheConfig.NixlProxyPort})
				}
			}

			// Decode-specific Nixl config
			if nodeType == "decode" {
				if nodeConfig.LMCacheConfig.NixlPeerHost != "" {
					// New naming: pd_peer_host
					env = append(env, corev1.EnvVar{Name: "LMCACHE_PD_PEER_HOST", Value: nodeConfig.LMCacheConfig.NixlPeerHost})
					env = append(env, corev1.EnvVar{Name: "LMCACHE_NIXL_PEER_HOST", Value: nodeConfig.LMCacheConfig.NixlPeerHost})
				}
				if nodeConfig.LMCacheConfig.NixlPeerInitPort != "" {
					// New naming: pd_peer_init_port
					env = append(env, corev1.EnvVar{Name: "LMCACHE_PD_PEER_INIT_PORT", Value: nodeConfig.LMCacheConfig.NixlPeerInitPort})
					env = append(env, corev1.EnvVar{Name: "LMCACHE_NIXL_PEER_INIT_PORT", Value: nodeConfig.LMCacheConfig.NixlPeerInitPort})
				}
				if nodeConfig.LMCacheConfig.NixlPeerAllocPort != "" {
					// New naming: pd_peer_alloc_port
					env = append(env, corev1.EnvVar{Name: "LMCACHE_PD_PEER_ALLOC_PORT", Value: nodeConfig.LMCacheConfig.NixlPeerAllocPort})
					env = append(env, corev1.EnvVar{Name: "LMCACHE_NIXL_PEER_ALLOC_PORT", Value: nodeConfig.LMCacheConfig.NixlPeerAllocPort})
				}
			}
		} else {
			env = append(env, corev1.EnvVar{Name: "LMCACHE_ENABLE_PD", Value: "False"})
			env = append(env, corev1.EnvVar{Name: "LMCACHE_ENABLE_NIXL", Value: "False"})
		}

		// Xpyd configuration
		if nodeConfig.LMCacheConfig.EnableXpyd {
			env = append(env, corev1.EnvVar{Name: "LMCACHE_ENABLE_XPYD", Value: "True"})
		} else {
			env = append(env, corev1.EnvVar{Name: "LMCACHE_ENABLE_XPYD", Value: "False"})
		}

		// RPC port
		if nodeConfig.LMCacheConfig.RPCPort != "" {
			env = append(env, corev1.EnvVar{Name: "LMCACHE_RPC_PORT", Value: nodeConfig.LMCacheConfig.RPCPort})
		}

		// Skip last N tokens (decode only)
		if nodeType == "decode" && nodeConfig.LMCacheConfig.SkipLastNTokens > 0 {
			env = append(env, corev1.EnvVar{Name: "LMCACHE_SKIP_LAST_N_TOKENS", Value: fmt.Sprintf("%d", nodeConfig.LMCacheConfig.SkipLastNTokens)})
		}
	}

	// Add user-defined environment variables
	if nodeConfig.VLLMConfig.Env != nil {
		for _, e := range nodeConfig.VLLMConfig.Env {
			env = append(env, corev1.EnvVar{Name: e.Name, Value: e.Value})
		}
	}

	return env
}

// buildResourceRequirementsForNode builds the resource requirements for a container for a specific node
func (r *VLLMRuntimeReconciler) buildResourceRequirementsForNode(res productionstackv1alpha1.ResourceRequirements) corev1.ResourceRequirements {
	resources := corev1.ResourceRequirements{
		Requests: corev1.ResourceList{},
		Limits:   corev1.ResourceList{},
	}

	if res.CPU != "" {
		resources.Requests[corev1.ResourceCPU] = resource.MustParse(res.CPU)
		resources.Limits[corev1.ResourceCPU] = resource.MustParse(res.CPU)
	}

	if res.Memory != "" {
		resources.Requests[corev1.ResourceMemory] = resource.MustParse(res.Memory)
		resources.Limits[corev1.ResourceMemory] = resource.MustParse(res.Memory)
	}

	if res.GPU != "" {
		gpuType := "nvidia.com/gpu"
		if res.GPUType != "" {
			gpuType = res.GPUType
		}
		gpuResource := resource.MustParse(res.GPU)
		resources.Requests[corev1.ResourceName(gpuType)] = gpuResource
		resources.Limits[corev1.ResourceName(gpuType)] = gpuResource
	}

	return resources
}

// buildVolumesAndMountsForNode builds volumes and volume mounts for the container for a specific node
func (r *VLLMRuntimeReconciler) buildVolumesAndMountsForNode(vllmRuntime *productionstackv1alpha1.VLLMRuntime, nodeConfig *productionstackv1alpha1.NodeConfig, nodeType string) ([]corev1.Volume, []corev1.VolumeMount) {
	var volumes []corev1.Volume
	var volumeMounts []corev1.VolumeMount

	if nodeConfig.StorageConfig.Enabled {
		volumeName := "pvc-storage"
		if nodeConfig.StorageConfig.VolumeName != "" {
			volumeName = nodeConfig.StorageConfig.VolumeName
		}

		mountPath := "/data"
		if nodeConfig.StorageConfig.MountPath != "" {
			mountPath = nodeConfig.StorageConfig.MountPath
		}

		pvcName := fmt.Sprintf("%s-%s", vllmRuntime.Name, nodeType)

		volumes = append(volumes, corev1.Volume{
			Name: volumeName,
			VolumeSource: corev1.VolumeSource{
				PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{
					ClaimName: pvcName,
				},
			},
		})

		volumeMounts = append(volumeMounts, corev1.VolumeMount{
			Name:      volumeName,
			MountPath: mountPath,
		})
	}

	return volumes, volumeMounts
}

// buildSidecarContainerForNode builds the sidecar container configuration for a specific node
func (r *VLLMRuntimeReconciler) buildSidecarContainerForNode(nodeConfig *productionstackv1alpha1.NodeConfig, volumeMounts []corev1.VolumeMount) corev1.Container {
	sidecarConfig := nodeConfig.DeploymentConfig.SidecarConfig

	// Build sidecar environment variables
	var sidecarEnv []corev1.EnvVar
	sidecarEnv = append(sidecarEnv,
		corev1.EnvVar{Name: "PORT", Value: "30090"},
		corev1.EnvVar{Name: "LORA_DOWNLOAD_BASE_DIR", Value: sidecarConfig.MountPath + "/lora-adapters"},
	)
	for _, envVar := range sidecarConfig.Env {
		sidecarEnv = append(sidecarEnv, corev1.EnvVar{Name: envVar.Name, Value: envVar.Value})
	}

	// Build sidecar resources
	sidecarResources := r.buildResourceRequirementsForNode(sidecarConfig.Resources)

	// Set defaults if not specified
	if sidecarConfig.Resources.CPU == "" {
		sidecarResources.Requests[corev1.ResourceCPU] = resource.MustParse("0.5")
		sidecarResources.Limits[corev1.ResourceCPU] = resource.MustParse("0.5")
	}
	if sidecarConfig.Resources.Memory == "" {
		sidecarResources.Requests[corev1.ResourceMemory] = resource.MustParse("128Mi")
		sidecarResources.Limits[corev1.ResourceMemory] = resource.MustParse("128Mi")
	}
	if sidecarConfig.Resources.GPU == "" {
		gpuType := "nvidia.com/gpu"
		if sidecarConfig.Resources.GPUType != "" {
			gpuType = sidecarConfig.Resources.GPUType
		}
		sidecarResources.Requests[corev1.ResourceName(gpuType)] = resource.MustParse("0")
		sidecarResources.Limits[corev1.ResourceName(gpuType)] = resource.MustParse("0")
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
		VolumeMounts:    volumeMounts,
	}

	return sidecarContainer
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
