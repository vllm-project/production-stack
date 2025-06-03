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
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// EDIT THIS FILE!  THIS IS SCAFFOLDING FOR YOU TO OWN!
// NOTE: json tags are required.  Any new fields you add must have json tags for the fields to be serialized.

// LoraAdapterSpec defines the desired state of LoraAdapter.
type LoraAdapterSpec struct {
	// AdapterSource defines where to get the LoRA adapter from.
	// +kubebuilder:validation:Required
	AdapterSource AdapterSource `json:"adapterSource"`
	// BaseModel is the name of the base model this adapter is for.
	// +kubebuilder:validation:Required
	BaseModel string `json:"baseModel"`
	// DeploymentConfig defines how the adapter should be deployed
	LoraAdapterDeploymentConfig LoraAdapterDeploymentConfig `json:"loraAdapterDeploymentConfig,omitempty"`
	// VLLMApiKey defines the configuration for vLLM API key authentication
	VLLMApiKey *VLLMApiKeyConfig `json:"vllmApiKey,omitempty"`
}

type AdapterSource struct {
	// AdapterName is the name of the adapter to apply.
	// +kubebuilder:validation:Required
	AdapterName string `json:"adapterName"`
	// AdapterPath is the path to the LoRA adapter weights. For local sources: required, specifies the path to the adapter For remote sources: optional, will be updated by the controller with the download path
	AdapterPath string `json:"adapterPath,omitempty"`
	// CredentialsSecretRef references a secret containing storage credentials.
	CredentialsSecretRef *SecretRef `json:"credentialsSecretRef,omitempty"`
	// MaxAdapters is the maximum number of adapters to load.
	MaxAdapters int32 `json:"maxAdapters,omitempty"`
	// Pattern is the pattern to use for the adapter name.
	Pattern string `json:"pattern,omitempty"`
	// Repository is the repository to get the LoRA adapter from.
	Repository *string `json:"repository,omitempty"`
	// Type is the type of the adapter source.
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Enum=local;s3;http;huggingface
	Type string `json:"type"`
}

// +mapType=atomic
type SecretRef struct {
	// Name of the referent. More info: https://kubernetes.io/docs/concepts/overview/working-with-objects/names/#names TODO: Add other useful fields. apiVersion, kind, uid?
	Name string `json:"name,omitempty"`
}

type LoraAdapterDeploymentConfig struct {
	// Algorithm specifies which placement algorithm to use.
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Enum=default;ordered;equalized
	// +kubebuilder:default=default
	Algorithm string `json:"algorithm"`
	// Replicas is the number of replicas that should load this adapter.
	// +kubebuilder:validation:Minimum=0
	Replicas *int32 `json:"replicas,omitempty"`
}

// VLLMApiKeyConfig defines how to obtain the vLLM API key
type VLLMApiKeyConfig struct {
	// Direct API key value
	// +optional
	Value string `json:"value,omitempty"`
	// Reference to a secret containing the API key
	// +optional
	SecretRef *VLLMApiKeySecretRef `json:"secretRef,omitempty"`
}

// VLLMApiKeySecretRef defines the reference to a secret containing the API key
type VLLMApiKeySecretRef struct {
	// Name of the secret
	// +kubebuilder:validation:Required
	SecretName string `json:"secretName"`
	// Key in the secret containing the API key
	// +kubebuilder:validation:Required
	SecretKey string `json:"secretKey"`
}

// LoraAdapterStatus defines the observed state of LoraAdapter.
type LoraAdapterStatus struct {
	// Condition contains details for one aspect of the current state of this API Resource.
	Conditions []Condition `json:"conditions,omitempty"`
	// LoadedAdapters tracks the loading status of adapters and their pod assignments.
	LoadedAdapters []LoadedAdapter `json:"loadedAdapters,omitempty"`
	// Message provides additional information about the current phase.
	Message string `json:"message,omitempty"`
	// Phase represents the current phase of the adapter deployment.
	Phase string `json:"phase,omitempty"`
	// ObservedGeneration represents the .metadata.generation that the condition was set based upon.
	// +kubebuilder:validation:Minimum=0
	ObservedGeneration int64 `json:"observedGeneration,omitempty"`
}

// Condition contains details for one aspect of the current state of this API Resource.
type Condition struct {
	// LastTransitionTime is the last time the condition transitioned from one status to another.
	// +kubebuilder:validation:Format=date-time
	// +kubebuilder:validation:Required
	LastTransitionTime metav1.Time `json:"lastTransitionTime"`
	// Message is a human-readable message indicating details about why the current state is set.
	// +kubebuilder:validation:MaxLength=32768
	// +kubebuilder:validation:Required
	Message string `json:"message"`
	// Reason is a brief reason for the condition's current status.
	// +kubebuilder:validation:MaxLength=1024
	// +kubebuilder:validation:MinLength=1
	// +kubebuilder:validation:Pattern=`^[A-Za-z]([A-Za-z0-9_,:]*[A-Za-z0-9_])?$`
	// +kubebuilder:validation:Required
	Reason string `json:"reason"`
	// Status is the status of the condition.
	// +kubebuilder:validation:Enum=True;False;Unknown
	// +kubebuilder:validation:Required
	Status string `json:"status"`
	// type of condition in CamelCase.
	// +kubebuilder:validation:MaxLength=316
	// +kubebuilder:validation:Pattern= ^([a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*/)?(([A-Za-z0-9][-A-Za-z0-9_.]*)?[A-Za-z0-9])$
	// +kubebuilder:validation:Required
	Type string `json:"type"`
}

// LoadedAdapter represents an adapter that has been loaded into a pod
type LoadedAdapter struct {
	// LoadTime is when the adapter was loaded
	// +kubebuilder:validation:Format=date-time
	LoadTime metav1.Time `json:"loadTime,omitempty"`
	// Name is the name of the adapter
	// +kubebuilder:validation:Required
	Name string `json:"name"`
	// Path is the path where the adapter is loaded
	// +kubebuilder:validation:Required
	Path string `json:"path"`
	// PodAssignments represents the pods this adapter has been assigned to
	PodAssignments PodAssignment `json:"podAssignments"`
	// Status is the status of the adapter
	// +kubebuilder:validation:Required
	Status string `json:"status"`
}

// PodAssignment represents a pod that has been assigned to load this adapter
type PodAssignment struct {
	// Pod represents the pod information
	// +kubebuilder:validation:Required
	PodName string `json:"podName"`
	// Namespace is the namespace of the pod
	// +kubebuilder:validation:Required
	Namespace string `json:"namespace"`
}

// // +mapType=atomic
// type ObjectReference struct {
// 	// APIVersion is the API version of the referent.
// 	APIVersion string `json:"apiVersion,omitempty"`
// 	// If referring to a piece of an object instead of an entire object.
// 	FieldPath string `json:"fieldPath,omitempty"`
// 	// Kind is the kind of the referent.
// 	Kind string `json:"kind,omitempty"`
// 	// Name is the name of the referent.
// 	Name string `json:"name,omitempty"`
// 	// Namespace is the namespace of the referent.
// 	Namespace string `json:"namespace,omitempty"`
// 	// ResourceVersion is the resource version of the referent.
// 	ResourceVersion string `json:"resourceVersion,omitempty"`
// 	// UID is the unique identifier of the referent.
// 	UID string `json:"uid,omitempty"`
// }

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status

// LoraAdapter is the Schema for the loraadapters API.
// +kubebuilder:printcolumn:name="Phase",type=string,JSONPath=`.status.phase`
// +kubebuilder:printcolumn:name="Age",type=date,JSONPath=`.metadata.creationTimestamp`
type LoraAdapter struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   LoraAdapterSpec   `json:"spec,omitempty"`
	Status LoraAdapterStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// LoraAdapterList contains a list of LoraAdapter.
type LoraAdapterList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []LoraAdapter `json:"items"`
}

func init() {
	SchemeBuilder.Register(&LoraAdapter{}, &LoraAdapterList{})
}
