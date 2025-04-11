package resources

import (
	"fmt"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/util/intstr"

	inferencev1alpha1 "github.com/vllm-project/production-stack/api/v1alpha1"
)

// BuildVLLMCommand builds the command for a vLLM component
func BuildVLLMCommand(engine *inferencev1alpha1.InferenceEngine, component string) []string {
	cmd := []string{
		"vllm",
		"serve",
		engine.Spec.ModelConfig.ModelName,
	}

	if engine.Spec.ModelConfig.TrustRemoteCode {
		cmd = append(cmd, "--trust-remote-code")
	}

	if engine.Spec.ModelConfig.MaxNumBatchedTokens > 0 {
		cmd = append(cmd, fmt.Sprintf("--max_num_batched_tokens=%d", engine.Spec.ModelConfig.MaxNumBatchedTokens))
	}

	// Add disaggregation-specific flags
	if engine.Spec.DeploymentMode == "disaggregated" {
		if component == "prefill" {
			cmd = append(cmd, "--mode=prefill")
			if engine.Spec.ModelConfig.EnableChunkedPrefill {
				cmd = append(cmd, "--enable-chunked-prefill")
			}
		} else if component == "decode" {
			cmd = append(cmd, "--mode=decode")
		}

		// Add KV transfer configuration if provided
		if engine.Spec.DisaggregationConfig != nil {
			kvConfig := engine.Spec.DisaggregationConfig.KVTransferConfig
			cmd = append(cmd, fmt.Sprintf("--kv-transfer-connector=%s", kvConfig.Connector))
			cmd = append(cmd, fmt.Sprintf("--kv-transfer-parallel-size=%d", kvConfig.ParallelSize))

			// Add component-specific configs
			for _, compConfig := range kvConfig.ComponentConfigs {
				if (component == "prefill" && compConfig.Role == "kv_producer") ||
					(component == "decode" && compConfig.Role == "kv_consumer") {
					cmd = append(cmd, fmt.Sprintf("--kv-transfer-rank=%d", compConfig.Rank))
					break
				}
			}
		}
	}

	return cmd
}

// CreatePVC creates a PersistentVolumeClaim for the model storage
func CreatePVC(engine *inferencev1alpha1.InferenceEngine) *corev1.PersistentVolumeClaim {
	return &corev1.PersistentVolumeClaim{
		ObjectMeta: metav1.ObjectMeta{
			Name:      engine.Name,
			Namespace: engine.Namespace,
			OwnerReferences: []metav1.OwnerReference{
				{
					APIVersion: inferencev1alpha1.GroupVersion.String(),
					Kind:       "InferenceEngine",
					Name:       engine.Name,
					UID:        engine.UID,
					Controller: &[]bool{true}[0],
				},
			},
		},
		Spec: corev1.PersistentVolumeClaimSpec{
			AccessModes: []corev1.PersistentVolumeAccessMode{
				corev1.ReadWriteOnce,
			},
			Resources: corev1.ResourceRequirements{
				Requests: corev1.ResourceList{
					corev1.ResourceStorage: resource.MustParse(engine.Spec.Storage.Size),
				},
			},
			StorageClassName: &engine.Spec.Storage.StorageClass,
		},
	}
}

// CreateBasicDeployment creates a deployment for the basic mode
func CreateBasicDeployment(engine *inferencev1alpha1.InferenceEngine) *appsv1.Deployment {
	labels := map[string]string{
		"app": engine.Name,
	}

	replicas := engine.Spec.Replicas["default"]
	resources := engine.Spec.Resources["default"]
	servicePort := engine.Spec.ServiceConfig["default"].Port

	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      engine.Name,
			Namespace: engine.Namespace,
			OwnerReferences: []metav1.OwnerReference{
				{
					APIVersion: inferencev1alpha1.GroupVersion.String(),
					Kind:       "InferenceEngine",
					Name:       engine.Name,
					UID:        engine.UID,
					Controller: &[]bool{true}[0],
				},
			},
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{
				MatchLabels: labels,
			},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
				},
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{
						{
							Name:    "vllm",
							Image:   "vllm/vllm-openai:latest",
							Command: BuildVLLMCommand(engine, "basic"),
							Ports: []corev1.ContainerPort{
								{
									Name:          "http",
									ContainerPort: servicePort,
								},
							},
							Resources: resources.ToResourceRequirements(),
							VolumeMounts: []corev1.VolumeMount{
								{
									Name:      "model-storage",
									MountPath: "/data",
								},
							},
						},
					},
					Volumes: []corev1.Volume{
						{
							Name: "model-storage",
							VolumeSource: corev1.VolumeSource{
								PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{
									ClaimName: engine.Name,
								},
							},
						},
					},
				},
			},
		},
	}
}

// CreatePrefillDeployment creates a deployment for the prefill component in disaggregated mode
func CreatePrefillDeployment(engine *inferencev1alpha1.InferenceEngine) *appsv1.Deployment {
	labels := map[string]string{
		"app":       engine.Name,
		"component": "prefill",
	}

	replicas := engine.Spec.Replicas["prefill"]
	resources := engine.Spec.Resources["prefill"]
	servicePort := engine.Spec.ServiceConfig["prefill"].Port

	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("%s-prefill", engine.Name),
			Namespace: engine.Namespace,
			OwnerReferences: []metav1.OwnerReference{
				{
					APIVersion: inferencev1alpha1.GroupVersion.String(),
					Kind:       "InferenceEngine",
					Name:       engine.Name,
					UID:        engine.UID,
					Controller: &[]bool{true}[0],
				},
			},
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{
				MatchLabels: labels,
			},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
				},
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{
						{
							Name:    "vllm-prefill",
							Image:   "vllm/vllm-openai:latest",
							Command: BuildVLLMCommand(engine, "prefill"),
							Ports: []corev1.ContainerPort{
								{
									Name:          "http",
									ContainerPort: servicePort,
								},
							},
							Resources: resources.ToResourceRequirements(),
							VolumeMounts: []corev1.VolumeMount{
								{
									Name:      "model-storage",
									MountPath: "/data",
								},
							},
						},
					},
					Volumes: []corev1.Volume{
						{
							Name: "model-storage",
							VolumeSource: corev1.VolumeSource{
								PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{
									ClaimName: engine.Name,
								},
							},
						},
					},
				},
			},
		},
	}
}

// CreateDecodeDeployment creates a deployment for the decode component in disaggregated mode
func CreateDecodeDeployment(engine *inferencev1alpha1.InferenceEngine) *appsv1.Deployment {
	labels := map[string]string{
		"app":       engine.Name,
		"component": "decode",
	}

	replicas := engine.Spec.Replicas["decode"]
	resources := engine.Spec.Resources["decode"]
	servicePort := engine.Spec.ServiceConfig["decode"].Port

	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("%s-decode", engine.Name),
			Namespace: engine.Namespace,
			OwnerReferences: []metav1.OwnerReference{
				{
					APIVersion: inferencev1alpha1.GroupVersion.String(),
					Kind:       "InferenceEngine",
					Name:       engine.Name,
					UID:        engine.UID,
					Controller: &[]bool{true}[0],
				},
			},
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{
				MatchLabels: labels,
			},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
				},
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{
						{
							Name:    "vllm-decode",
							Image:   "vllm/vllm-openai:latest",
							Command: BuildVLLMCommand(engine, "decode"),
							Ports: []corev1.ContainerPort{
								{
									Name:          "http",
									ContainerPort: servicePort,
								},
							},
							Resources: resources.ToResourceRequirements(),
							VolumeMounts: []corev1.VolumeMount{
								{
									Name:      "model-storage",
									MountPath: "/data",
								},
							},
						},
					},
					Volumes: []corev1.Volume{
						{
							Name: "model-storage",
							VolumeSource: corev1.VolumeSource{
								PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{
									ClaimName: engine.Name,
								},
							},
						},
					},
				},
			},
		},
	}
}

// CreateService creates a service for a component
func CreateService(engine *inferencev1alpha1.InferenceEngine, component string) *corev1.Service {
	var serviceName, selectorComponent string
	var servicePort int32
	var serviceType string

	if component == "basic" {
		serviceName = engine.Name
		selectorComponent = ""
		serviceConfig := engine.Spec.ServiceConfig["default"]
		servicePort = serviceConfig.Port
		serviceType = serviceConfig.Type
	} else {
		serviceName = fmt.Sprintf("%s-%s", engine.Name, component)
		selectorComponent = component
		serviceConfig := engine.Spec.ServiceConfig[component]
		servicePort = serviceConfig.Port
		serviceType = serviceConfig.Type
	}

	selector := map[string]string{
		"app": engine.Name,
	}

	if selectorComponent != "" {
		selector["component"] = selectorComponent
	}

	return &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      serviceName,
			Namespace: engine.Namespace,
			OwnerReferences: []metav1.OwnerReference{
				{
					APIVersion: inferencev1alpha1.GroupVersion.String(),
					Kind:       "InferenceEngine",
					Name:       engine.Name,
					UID:        engine.UID,
					Controller: &[]bool{true}[0],
				},
			},
		},
		Spec: corev1.ServiceSpec{
			Selector: selector,
			Ports: []corev1.ServicePort{
				{
					Name:       "http",
					Port:       servicePort,
					TargetPort: intstr.FromString("http"),
					Protocol:   corev1.ProtocolTCP,
				},
			},
			Type: corev1.ServiceType(serviceType),
		},
	}
}

// CreateProxyDeployment creates a deployment for the proxy component in disaggregated mode
func CreateProxyDeployment(engine *inferencev1alpha1.InferenceEngine) *appsv1.Deployment {
	if engine.Spec.DisaggregationConfig == nil || engine.Spec.DisaggregationConfig.ProxyConfig == nil {
		return nil
	}

	labels := map[string]string{
		"app":       engine.Name,
		"component": "proxy",
	}

	replicas := engine.Spec.Replicas["proxy"]
	resources := engine.Spec.Resources["proxy"]
	servicePort := engine.Spec.ServiceConfig["proxy"].Port
	proxyImage := "vllm/vllm-proxy:latest"

	if engine.Spec.DisaggregationConfig.ProxyConfig.Image != "" {
		proxyImage = engine.Spec.DisaggregationConfig.ProxyConfig.Image
	}

	// Create environment variables from the proxy config
	envVars := []corev1.EnvVar{}
	if engine.Spec.DisaggregationConfig.ProxyConfig.Config != nil {
		for k, v := range engine.Spec.DisaggregationConfig.ProxyConfig.Config {
			envVars = append(envVars, corev1.EnvVar{
				Name:  k,
				Value: v,
			})
		}
	}

	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("%s-proxy", engine.Name),
			Namespace: engine.Namespace,
			OwnerReferences: []metav1.OwnerReference{
				{
					APIVersion: inferencev1alpha1.GroupVersion.String(),
					Kind:       "InferenceEngine",
					Name:       engine.Name,
					UID:        engine.UID,
					Controller: &[]bool{true}[0],
				},
			},
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{
				MatchLabels: labels,
			},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
				},
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{
						{
							Name:  "vllm-proxy",
							Image: proxyImage,
							Env:   envVars,
							Ports: []corev1.ContainerPort{
								{
									Name:          "http",
									ContainerPort: servicePort,
								},
							},
							Resources: resources.ToResourceRequirements(),
						},
					},
				},
			},
		},
	}
}
