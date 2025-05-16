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

// VLLMRuntimeSpec defines the desired state of VLLMRuntime
type VLLMRuntimeSpec struct {
	// Model configuration
	Model ModelSpec `json:"model"`

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

	// LM Cache configuration
	LMCacheConfig LMCacheConfig `json:"lmCacheConfig,omitempty"`

	// Extra arguments for vllm serve
	ExtraArgs []string `json:"extraArgs,omitempty"`

	// Use V1 API
	V1 bool `json:"v1,omitempty"`

	// Port for vLLM server
	// +kubebuilder:default=8000
	Port int32 `json:"port,omitempty"`

	// Environment variables
	Env []EnvVar `json:"env,omitempty"`

	// Resource requirements
	Resources ResourceRequirements `json:"resources"`

	// Image configuration
	Image ImageSpec `json:"image"`

	// HuggingFace token secret
	HFTokenSecret corev1.LocalObjectReference `json:"hfTokenSecret,omitempty"`
	// +kubebuilder:default=token
	// +kubebuilder:validation:RequiredWhen=HFTokenSecret.Name!=""
	HFTokenName string `json:"hfTokenName,omitempty"`

	// Replicas
	// +kubebuilder:default=1
	Replicas int32 `json:"replicas,omitempty"`

	// Deploy strategy
	// +kubebuilder:validation:Enum=RollingUpdate;Recreate
	// +kubebuilder:default=RollingUpdate
	DeployStrategy string `json:"deploymentStrategy,omitempty"`
}

// ModelSpec defines the model configuration
type ModelSpec struct {
	// Model URL
	ModelURL string `json:"modelURL"`

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
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
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
