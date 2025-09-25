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

// VLLMRouterSpec defines the desired state of VLLMRouter
type VLLMRouterSpec struct {
	// EnableRouter determines if the router should be deployed
	// +kubebuilder:default=true
	EnableRouter bool `json:"enableRouter,omitempty"`

	// Replicas specifies the number of router replicas
	// +kubebuilder:default=1
	Replicas int32 `json:"replicas,omitempty"`

	// ServiceDiscovery specifies the service discovery method (k8s or static)
	// +kubebuilder:validation:Enum=k8s;static
	// +kubebuilder:default=k8s
	ServiceDiscovery string `json:"serviceDiscovery,omitempty"`

	// K8sLabelSelector specifies the label selector for vLLM runtime pods when using k8s service discovery
	// +kubebuilder:validation:RequiredWhen=ServiceDiscovery=k8s
	K8sLabelSelector string `json:"k8sLabelSelector,omitempty"`

	// StaticBackends is required when using static service discovery
	// +kubebuilder:validation:RequiredWhen=ServiceDiscovery=static
	StaticBackends string `json:"staticBackends,omitempty"`

	// StaticModels is required when using static service discovery
	// +kubebuilder:validation:RequiredWhen=ServiceDiscovery=static
	StaticModels string `json:"staticModels,omitempty"`

	// RoutingLogic specifies the routing strategy
	// +kubebuilder:validation:Enum=roundrobin;session
	// +kubebuilder:default=roundrobin
	RoutingLogic string `json:"routingLogic,omitempty"`

	// SessionKey for session-based routing
	// +kubebuilder:validation:RequiredWhen=RoutingLogic=session
	// +kubebuilder:default=""
	SessionKey string `json:"sessionKey,omitempty"`

	// EngineScrapeInterval for collecting engine statistics
	EngineScrapeInterval int32 `json:"engineScrapeInterval,omitempty"`

	// RequestStatsWindow for request statistics
	RequestStatsWindow int32 `json:"requestStatsWindow,omitempty"`

	// ExtraArgs for additional router arguments
	ExtraArgs []string `json:"extraArgs,omitempty"`

	// NodeSelectorTerms for pod scheduling
	NodeSelectorTerms []corev1.NodeSelectorTerm `json:"nodeSelectorTerms,omitempty"`

	// ServiceAccountName for the router pod
	ServiceAccountName string `json:"serviceAccountName,omitempty"`

	// ContainerPort for the router service
	// +kubebuilder:default=80
	Port int32 `json:"port,omitempty"`

	// Image configuration
	Image ImageSpec `json:"image"`

	// Resource requirements
	Resources ResourceRequirements `json:"resources"`

	// Environment variables
	Env []EnvVar `json:"env,omitempty"`

	// VLLM API Key configuration
	VLLMApiKeySecret corev1.LocalObjectReference `json:"vllmApiKeySecret,omitempty"`
	VLLMApiKeyName   string                      `json:"vllmApiKeyName,omitempty"`
}

// VLLMRouterStatus defines the observed state of VLLMRouter
type VLLMRouterStatus struct {
	// Router status
	Status string `json:"status,omitempty"`

	// Last updated timestamp
	LastUpdated metav1.Time `json:"lastUpdated,omitempty"`

	// Number of active runtimes
	ActiveRuntimes int32 `json:"activeRuntimes,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status

// VLLMRouter is the Schema for the vllmrouters API
type VLLMRouter struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   VLLMRouterSpec   `json:"spec,omitempty"`
	Status VLLMRouterStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// VLLMRouterList contains a list of VLLMRouter
type VLLMRouterList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []VLLMRouter `json:"items"`
}

func init() {
	SchemeBuilder.Register(&VLLMRouter{}, &VLLMRouterList{})
}
