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

package v1alpha1

import (
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// EDIT THIS FILE!  THIS IS SCAFFOLDING FOR YOU TO OWN!
// NOTE: json tags are required.  Any new fields you add must have json tags for the fields to be serialized.

// ComponentResources defines the resource requirements for a component
type ComponentResources struct {
	// Limits describes the maximum amount of compute resources allowed.
	// More info: https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/
	// +optional
	Limits corev1.ResourceList `json:"limits,omitempty"`
	// Requests describes the minimum amount of compute resources required.
	// More info: https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/
	// +optional
	Requests corev1.ResourceList `json:"requests,omitempty"`
}

// ToResourceRequirements converts ComponentResources to corev1.ResourceRequirements
func (cr *ComponentResources) ToResourceRequirements() corev1.ResourceRequirements {
	return corev1.ResourceRequirements{
		Limits:   cr.Limits,
		Requests: cr.Requests,
	}
}

// InferenceEngineSpec defines the desired state of InferenceEngine
type InferenceEngineSpec struct {
	// ModelConfig specifies the model configuration
	// +kubebuilder:validation:Required
	ModelConfig ModelConfig `json:"modelConfig"`

	// DeploymentMode specifies how the engine should be deployed (e.g., basic, disaggregated)
	// +kubebuilder:validation:Enum=basic;disaggregated
	// +kubebuilder:default=basic
	DeploymentMode string `json:"deploymentMode,omitempty"`

	// Resources specifies the resource requirements for each component
	// If DeploymentMode is basic, only the "default" key is used
	// If DeploymentMode is disaggregated, keys like "prefill", "decode" can be used
	// +kubebuilder:validation:Required
	Resources map[string]ComponentResources `json:"resources"`

	// Replicas specifies the number of replicas for each component
	// If DeploymentMode is basic, only the "default" key is used
	// If DeploymentMode is disaggregated, keys like "prefill", "decode" can be used
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:MinProperties=1
	Replicas map[string]int32 `json:"replicas"`

	// Storage specifies the storage configuration
	// +kubebuilder:validation:Required
	Storage StorageConfig `json:"storage"`

	// ServiceConfig specifies the service configuration for each component
	// If DeploymentMode is basic, only the "default" key is used
	// If DeploymentMode is disaggregated, keys like "prefill", "decode", "proxy" can be used
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:MinProperties=1
	ServiceConfig map[string]ServiceConfig `json:"serviceConfig"`

	// DisaggregationConfig specifies the configuration for disaggregated deployment
	// +optional
	DisaggregationConfig *DisaggregationConfig `json:"disaggregationConfig,omitempty"`
}

// ModelConfig defines the model configuration
type ModelConfig struct {
	// ModelName specifies the name of the model
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:MinLength=1
	ModelName string `json:"modelName"`

	// TrustRemoteCode specifies whether to trust remote code
	// +kubebuilder:default=false
	TrustRemoteCode bool `json:"trustRemoteCode,omitempty"`

	// MaxNumBatchedTokens specifies the maximum number of batched tokens
	// +kubebuilder:default=2048
	// +kubebuilder:validation:Minimum=1
	MaxNumBatchedTokens int32 `json:"maxNumBatchedTokens,omitempty"`

	// EnableChunkedPrefill specifies whether to enable chunked prefill
	// +kubebuilder:default=false
	EnableChunkedPrefill bool `json:"enableChunkedPrefill,omitempty"`
}

// StorageConfig defines the storage configuration
type StorageConfig struct {
	// Size specifies the size of the storage
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Pattern=^[0-9]+[KMGT]i?$
	Size string `json:"size"`

	// StorageClass specifies the storage class
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:MinLength=1
	StorageClass string `json:"storageClass"`
}

// ServiceConfig defines the service configuration
type ServiceConfig struct {
	// Port specifies the service port
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:validation:Maximum=65535
	Port int32 `json:"port"`

	// Type specifies the service type
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Enum=ClusterIP;NodePort;LoadBalancer
	Type string `json:"type"`
}

// DisaggregationConfig defines the configuration for disaggregated deployment
type DisaggregationConfig struct {
	// KVTransferConfig specifies the configuration for KV cache transfer
	// +kubebuilder:validation:Required
	KVTransferConfig KVTransferConfig `json:"kvTransferConfig"`

	// ProxyConfig specifies the configuration for the proxy component
	// +optional
	ProxyConfig *ProxyConfig `json:"proxyConfig,omitempty"`
}

// KVTransferConfig defines the configuration for KV cache transfer
type KVTransferConfig struct {
	// Connector specifies the type of connector (e.g., "PyNcclConnector")
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:MinLength=1
	Connector string `json:"connector"`

	// ParallelSize specifies the total number of parallel components
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Minimum=1
	ParallelSize int32 `json:"parallelSize"`

	// ComponentConfigs specifies the configuration for each component
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:MinItems=1
	ComponentConfigs []KVComponentConfig `json:"componentConfigs"`
}

// KVComponentConfig defines the configuration for a KV cache component
type KVComponentConfig struct {
	// Role specifies the role of the component (e.g., "kv_producer", "kv_consumer")
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:MinLength=1
	// +kubebuilder:validation:Enum=kv_producer;kv_consumer
	Role string `json:"role"`

	// Rank specifies the rank of the component
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Minimum=0
	Rank int32 `json:"rank"`

	// AdditionalConfig specifies additional component-specific configuration
	// +optional
	AdditionalConfig map[string]string `json:"additionalConfig,omitempty"`
}

// ProxyConfig defines the configuration for the proxy component
type ProxyConfig struct {
	// Image specifies the proxy image
	// +optional
	Image string `json:"image,omitempty"`

	// Config specifies proxy-specific configuration
	// +optional
	Config map[string]string `json:"config,omitempty"`
}

// InferenceEngineStatus defines the observed state of InferenceEngine
type InferenceEngineStatus struct {
	// Phase represents the current phase of the inference engine
	// +kubebuilder:validation:Enum=Pending;Running;Failed
	Phase InferenceEnginePhase `json:"phase"`

	// Message provides a human-readable message about the current state
	Message string `json:"message,omitempty"`

	// Conditions represents the latest available observations of the inference engine's state
	Conditions []metav1.Condition `json:"conditions,omitempty"`
}

// InferenceEnginePhase represents the phase of the inference engine
type InferenceEnginePhase string

const (
	// InferenceEnginePhasePending indicates that the inference engine is pending
	InferenceEnginePhasePending InferenceEnginePhase = "Pending"

	// InferenceEnginePhaseRunning indicates that the inference engine is running
	InferenceEnginePhaseRunning InferenceEnginePhase = "Running"

	// InferenceEnginePhaseFailed indicates that the inference engine has failed
	InferenceEnginePhaseFailed InferenceEnginePhase = "Failed"
)

//+kubebuilder:object:root=true
//+kubebuilder:subresource:status
//+kubebuilder:printcolumn:name="Phase",type="string",JSONPath=".status.phase"
//+kubebuilder:printcolumn:name="Age",type="date",JSONPath=".metadata.creationTimestamp"
//+kubebuilder:resource:scope=Namespaced,shortName=ie
//+kubebuilder:metadata:annotations="api-approved.kubernetes.io=https://github.com/vllm-project/vllm-pd-disagg-config"

// InferenceEngine is the Schema for the inferenceengines API
type InferenceEngine struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   InferenceEngineSpec   `json:"spec,omitempty"`
	Status InferenceEngineStatus `json:"status,omitempty"`
}

//+kubebuilder:object:root=true

// InferenceEngineList contains a list of InferenceEngine
type InferenceEngineList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []InferenceEngine `json:"items"`
}

func init() {
	SchemeBuilder.Register(&InferenceEngine{}, &InferenceEngineList{})
}
