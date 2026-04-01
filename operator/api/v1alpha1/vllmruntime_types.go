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

package v1alpha1

import (
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// EDIT THIS FILE!  THIS IS SCAFFOLDING FOR YOU TO OWN!
// NOTE: json tags are required.  Any new fields you add must have json tags for the fields to be serialized.

// DeploymentConfig defines the deployment configuration
type DeploymentConfig struct {
	// Replicas
	// +kubebuilder:default=1
	Replicas int32 `json:"replicas,omitempty"`

	// Node selector
	NodeSelectorTerms []corev1.NodeSelectorTerm `json:"nodeSelectorTerms,omitempty"`

	// Toleration
	Toleration []corev1.Toleration `json:"toleration,omitempty"`

	// Deploy strategy
	// +kubebuilder:validation:Enum=RollingUpdate;Recreate
	// +kubebuilder:default=RollingUpdate
	DeployStrategy string `json:"deploymentStrategy,omitempty"`

	// Resource requirements
	Resources ResourceRequirements `json:"resources"`

	// Image configuration
	Image ImageSpec `json:"image"`

	// Sidecar configuration
	SidecarConfig SidecarConfig `json:"sidecarConfig,omitempty"`
}

// ScaleUpPolicy defines the HPA scaling behavior when scaling up
type ScaleUpPolicy struct {
	// StabilizationWindowSeconds is the HPA stabilization window for scaling up
	// +kubebuilder:default=0
	StabilizationWindowSeconds *int32 `json:"stabilizationWindowSeconds,omitempty"`

	// PodValue is the max pods to add per period
	// +kubebuilder:default=1
	// +kubebuilder:validation:Minimum=1
	PodValue *int32 `json:"podValue,omitempty"`

	// PeriodSeconds is the period for the scale up policy
	// +kubebuilder:default=60
	// +kubebuilder:validation:Minimum=1
	PeriodSeconds *int32 `json:"periodSeconds,omitempty"`
}

// ScaleDownPolicy defines the HPA scaling behavior when scaling down
type ScaleDownPolicy struct {
	// StabilizationWindowSeconds is the HPA stabilization window for scaling down
	// +kubebuilder:default=300
	StabilizationWindowSeconds *int32 `json:"stabilizationWindowSeconds,omitempty"`

	// PodValue is the max pods to remove per period
	// +kubebuilder:default=1
	// +kubebuilder:validation:Minimum=1
	PodValue *int32 `json:"podValue,omitempty"`

	// PeriodSeconds is the period for the scale down policy
	// +kubebuilder:default=60
	// +kubebuilder:validation:Minimum=1
	PeriodSeconds *int32 `json:"periodSeconds,omitempty"`

	// ScaleToZeroDelaySeconds is the wait time before scaling to zero (seconds).
	// Only applicable when minReplicas is set to 0.
	// +kubebuilder:default=1800
	ScaleToZeroDelaySeconds *int32 `json:"scaleToZeroDelaySeconds,omitempty"`
}

// TriggerConfig defines the metric thresholds for autoscaling triggers
type TriggerConfig struct {
	// PrometheusAddress is the Prometheus server address for metric queries
	// +kubebuilder:default="http://kube-prom-stack-kube-prome-prometheus.monitoring.svc:9090"
	PrometheusAddress string `json:"prometheusAddress,omitempty"`

	// RequestsRunningThreshold is the per-pod concurrent requests threshold for scaling
	// +kubebuilder:default=5
	// +kubebuilder:validation:Minimum=1
	RequestsRunningThreshold *int32 `json:"requestsRunningThreshold,omitempty"`

	// GenerationTokensThreshold is the per-pod generation tokens/s threshold for scaling
	// +kubebuilder:default=100
	// +kubebuilder:validation:Minimum=1
	GenerationTokensThreshold *int32 `json:"generationTokensThreshold,omitempty"`

	// PromptTokensThreshold is the per-pod prompt tokens/s threshold for scaling
	// +kubebuilder:default=100
	// +kubebuilder:validation:Minimum=1
	PromptTokensThreshold *int32 `json:"promptTokensThreshold,omitempty"`
}

// AutoscalingConfig defines the KEDA autoscaling configuration
type AutoscalingConfig struct {
	// Enabled enables autoscaling
	Enabled bool `json:"enabled,omitempty"`

	// MinReplicas is the minimum number of replicas (defaults to 1, set to 0 to enable scale-to-zero)
	// +kubebuilder:default=1
	// +kubebuilder:validation:Minimum=0
	MinReplicas *int32 `json:"minReplicas,omitempty"`

	// MaxReplicas is the maximum number of replicas
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Minimum=1
	MaxReplicas int32 `json:"maxReplicas"`

	// PollingInterval is how often KEDA checks metrics (seconds)
	// +kubebuilder:default=15
	PollingInterval *int32 `json:"pollingInterval,omitempty"`

	// ScaleUpPolicy defines the scaling behavior when scaling up
	ScaleUpPolicy ScaleUpPolicy `json:"scaleUpPolicy,omitempty"`

	// ScaleDownPolicy defines the scaling behavior when scaling down
	ScaleDownPolicy ScaleDownPolicy `json:"scaleDownPolicy,omitempty"`

	// Triggers defines the metric thresholds for autoscaling
	Triggers TriggerConfig `json:"triggers,omitempty"`
}

// VLLMRuntimeSpec defines the desired state of VLLMRuntime
type VLLMRuntimeSpec struct {
	// Model configuration
	Model ModelSpec `json:"model"`

	// vLLM server configuration
	VLLMConfig VLLMConfig `json:"vllmConfig"`

	// LM Cache configuration
	LMCacheConfig LMCacheConfig `json:"lmCacheConfig,omitempty"`

	// Storage configuration
	StorageConfig StorageConfig `json:"storageConfig,omitempty"`

	// Deployment configuration
	DeploymentConfig DeploymentConfig `json:"deploymentConfig"`

	// Autoscaling configuration
	AutoscalingConfig *AutoscalingConfig `json:"autoscalingConfig,omitempty"`
}

// VLLMConfig defines the vLLM server configuration
type VLLMConfig struct {
	// Enable chunked prefill
	EnableChunkedPrefill bool `json:"enableChunkedPrefill,omitempty"`

	// Enable prefix caching
	EnablePrefixCaching bool `json:"enablePrefixCaching,omitempty"`

	// Tensor parallel size
	TensorParallelSize int32 `json:"tensorParallelSize,omitempty"`

	// GPU memory utilization
	GpuMemoryUtilization string `json:"gpuMemoryUtilization,omitempty"`

	// Maximum number of LoRAs
	MaxLoras int32 `json:"maxLoras,omitempty"`

	// Extra arguments for vllm serve
	ExtraArgs []string `json:"extraArgs,omitempty"`

	// Use V1 API
	V1 bool `json:"v1,omitempty"`

	// Port for vLLM server
	// +kubebuilder:default=8000
	Port int32 `json:"port,omitempty"`

	// Environment variables
	Env []EnvVar `json:"env,omitempty"`
}

// ModelSpec defines the model configuration
type ModelSpec struct {
	// Model URL
	ModelURL string `json:"modelURL"`

	// HuggingFace token secret
	HFTokenSecret HuggingFaceTokenSecret `json:"hfTokenSecret,omitempty"`

	// Enable LoRA
	EnableLoRA bool `json:"enableLoRA,omitempty"`

	// Enable tool
	EnableTool bool `json:"enableTool,omitempty"`

	// Tool call parser
	ToolCallParser string `json:"toolCallParser,omitempty"`

	// Maximum model length
	MaxModelLen int32 `json:"maxModelLen,omitempty"`

	// Data type
	DType string `json:"dtype,omitempty"`

	// Maximum number of sequences
	MaxNumSeqs int32 `json:"maxNumSeqs,omitempty"`

	// Chat template
	ChatTemplate string `json:"chatTemplate,omitempty"`
}

type HuggingFaceTokenSecret struct {
	// HuggingFace token secret name
	HFTokenSecretName string `json:"hfTokenSecretName,omitempty"`

	// HuggingFace token key name in the secret
	// +kubebuilder:default=token
	// +kubebuilder:validation:RequiredWhen=HFTokenSecret.Name!=""
	HFTokenKeyName string `json:"hfTokenKeyName,omitempty"`
}

// LMCacheConfig defines the LM Cache configuration
type LMCacheConfig struct {
	// Enabled enables LM Cache
	// +kubebuilder:default=false
	Enabled bool `json:"enabled,omitempty"`

	// CPUOffloadingBufferSize is the size of the CPU offloading buffer
	// +kubebuilder:default="4Gi"
	CPUOffloadingBufferSize string `json:"cpuOffloadingBufferSize,omitempty"`

	// DiskOffloadingBufferSize is the size of the disk offloading buffer
	// +kubebuilder:default="8Gi"
	DiskOffloadingBufferSize string `json:"diskOffloadingBufferSize,omitempty"`

	// RemoteURL is the URL of the remote cache server
	RemoteURL string `json:"remoteUrl,omitempty"`

	// RemoteSerde is the serialization format for the remote cache
	RemoteSerde string `json:"remoteSerde,omitempty"`
}

// StorageConfig defines the storage configuration
type StorageConfig struct {
	// Enabled enables persistent storage
	// +kubebuilder:default=false
	Enabled bool `json:"enabled,omitempty"`

	// StorageClassName is the name of the storage class to use
	StorageClassName string `json:"storageClassName,omitempty"`

	// Size is the size of the persistent volume claim
	// +kubebuilder:default="10Gi"
	Size string `json:"size,omitempty"`

	// AccessMode is the access mode for the persistent volume claim
	// +kubebuilder:default=ReadWriteMany
	// +kubebuilder:validation:Enum=ReadWriteOnce;ReadOnlyMany;ReadWriteMany
	AccessMode string `json:"accessMode,omitempty"`

	// MountPath is the path where the volume will be mounted in the container
	// +kubebuilder:default="/data"
	MountPath string `json:"mountPath,omitempty"`

	// VolumeName is the name of the volume (optional, will be auto-generated if not specified)
	// +kubebuilder:default="pvc-storage"
	VolumeName string `json:"volumeName,omitempty"`
}

// SidecarConfig defines the sidecar container configuration
type SidecarConfig struct {
	// Enabled enables the sidecar container
	// +kubebuilder:default=false
	Enabled bool `json:"enabled,omitempty"`

	// Name is the name of the sidecar container
	// +kubebuilder:default="sidecar"
	Name string `json:"name,omitempty"`

	// Image configuration for the sidecar
	Image ImageSpec `json:"image"`

	// Command to run in the sidecar container
	Command []string `json:"command,omitempty"`

	// Arguments for the sidecar container
	Args []string `json:"args,omitempty"`

	// Environment variables for the sidecar container
	Env []EnvVar `json:"env,omitempty"`

	// Resource requirements for the sidecar container
	Resources ResourceRequirements `json:"resources,omitempty"`

	// MountPath is the path where the shared volume will be mounted in the sidecar
	// +kubebuilder:default="/data"
	MountPath string `json:"mountPath,omitempty"`
}

// EnvVar represents an environment variable
type EnvVar struct {
	Name  string `json:"name"`
	Value string `json:"value"`
}

// VLLMRuntimeStatus defines the observed state of VLLMRuntime
type VLLMRuntimeStatus struct {
	// Model status
	ModelStatus string `json:"modelStatus,omitempty"`

	// Last updated timestamp
	LastUpdated metav1.Time `json:"lastUpdated,omitempty"`

	// Current replica count (used by scale subresource)
	Replicas int32 `json:"replicas,omitempty"`

	// Label selector for pods (used by scale subresource for HPA AverageValue)
	Selector string `json:"selector,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:subresource:scale:specpath=.spec.deploymentConfig.replicas,statuspath=.status.replicas,selectorpath=.status.selector
// +kubebuilder:resource:shortName=vr

// VLLMRuntime is the Schema for the vllmruntimes API
type VLLMRuntime struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   VLLMRuntimeSpec   `json:"spec,omitempty"`
	Status VLLMRuntimeStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// VLLMRuntimeList contains a list of VLLMRuntime
type VLLMRuntimeList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []VLLMRuntime `json:"items"`
}

func init() {
	SchemeBuilder.Register(&VLLMRuntime{}, &VLLMRuntimeList{})
}
