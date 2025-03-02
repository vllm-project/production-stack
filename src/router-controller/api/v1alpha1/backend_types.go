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
	"encoding/json"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// BackendSpec defines the desired state of Backend
type BackendSpec struct {
	// INSERT ADDITIONAL SPEC FIELDS - desired state of cluster
	// Important: Run "make" to regenerate code after modifying this file

	// Type specifies the type of backend
	// +kubebuilder:validation:Enum=vllm;openai;ollama
	// +kubebuilder:default=vllm
	Type string `json:"type"`

	// Endpoint defines how to connect to the backend service
	// +kubebuilder:validation:Required
	Endpoint BackendEndpoint `json:"endpoint"`

	// Models is a comma-separated list of model names supported by this backend
	// +kubebuilder:validation:Required
	Models string `json:"models"`

	// ServiceRef is a reference to the backend service in Kubernetes (optional)
	// Deprecated: Use Endpoint.Service instead
	// +optional
	ServiceRef *corev1.ObjectReference `json:"serviceRef,omitempty"`

	// AuthSecret is a reference to a secret containing authentication information (optional)
	// +optional
	AuthSecret *corev1.SecretReference `json:"authSecret,omitempty"`

	// SecretRef is a reference to a secret containing API keys for this backend
	// +optional
	SecretRef *SecretReference `json:"secretRef,omitempty"`

	// HealthCheck defines the health check configuration for the backend
	// +optional
	HealthCheck *HealthCheckConfig `json:"healthCheck,omitempty"`

	// MaxConcurrentRequests is the maximum number of concurrent requests this backend can handle
	// +optional
	// +kubebuilder:default=100
	// +kubebuilder:validation:Minimum=1
	MaxConcurrentRequests int32 `json:"maxConcurrentRequests,omitempty"`

	// Timeout is the request timeout in seconds
	// +optional
	// +kubebuilder:default=300
	// +kubebuilder:validation:Minimum=1
	Timeout int32 `json:"timeout,omitempty"`
}

// BackendEndpoint defines how to connect to a backend service
// Only one of the fields should be specified
// +kubebuilder:validation:MaxProperties=1
type BackendEndpoint struct {
	// URL is a direct URL to the backend service
	// +optional
	// +kubebuilder:validation:Pattern=`^(http|https)://[^\s/$.?#].[^\s]*$`
	URL string `json:"url,omitempty"`

	// Service is a reference to a Kubernetes service
	// +optional
	Service *ServiceEndpoint `json:"service,omitempty"`

	// FQDN is a fully qualified domain name endpoint
	// +optional
	FQDN *FQDNEndpoint `json:"fqdn,omitempty"`

	// IP is an IP address endpoint
	// +optional
	IP *IPEndpoint `json:"ip,omitempty"`

	// Unix is a unix domain socket endpoint
	// +optional
	Unix *UnixSocketEndpoint `json:"unix,omitempty"`
}

// UnmarshalJSON implements the json.Unmarshaler interface for BackendEndpoint
// This allows handling both string URLs and structured endpoint objects
func (be *BackendEndpoint) UnmarshalJSON(data []byte) error {
	// First try to unmarshal as a string (for backward compatibility)
	var urlStr string
	if err := json.Unmarshal(data, &urlStr); err == nil {
		// If successful, treat the string as a URL
		be.URL = urlStr
		return nil
	}

	// If not a string, try to unmarshal as a structured object
	type BackendEndpointAlias BackendEndpoint
	alias := &BackendEndpointAlias{}
	if err := json.Unmarshal(data, alias); err != nil {
		return err
	}

	*be = BackendEndpoint(*alias)
	return nil
}

// ServiceEndpoint defines a reference to a Kubernetes service
type ServiceEndpoint struct {
	// Reference to a Kubernetes service
	// +kubebuilder:validation:Required
	ObjectReference corev1.ObjectReference `json:"objectReference"`

	// Port is the port number of the service
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:validation:Maximum=65535
	Port int32 `json:"port"`

	// TargetPort is the target port of the service
	// +optional
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:validation:Maximum=65535
	TargetPort int32 `json:"targetPort,omitempty"`
}

// FQDNEndpoint defines a fully qualified domain name endpoint
type FQDNEndpoint struct {
	// Hostname is the FQDN hostname
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Pattern=`^([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])(\.([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]{0,61}[a-zA-Z0-9]))*$`
	Hostname string `json:"hostname"`

	// Port is the port number
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:validation:Maximum=65535
	Port int32 `json:"port"`
}

// IPEndpoint defines an IP address endpoint
type IPEndpoint struct {
	// Address is the IP address
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Pattern=`^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])$|^(([0-9a-fA-F]{1,4}:){7,7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|:((:[0-9a-fA-F]{1,4}){1,7}|:)|fe80:(:[0-9a-fA-F]{0,4}){0,4}%[0-9a-zA-Z]{1,}|::(ffff(:0{1,4}){0,1}:){0,1}((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])|([0-9a-fA-F]{1,4}:){1,4}:((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9]))$`
	Address string `json:"address"`

	// Port is the port number
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:validation:Maximum=65535
	Port int32 `json:"port"`
}

// UnixSocketEndpoint defines a unix domain socket endpoint
type UnixSocketEndpoint struct {
	// Path is the path to the unix domain socket
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Pattern=`^/[a-zA-Z0-9_\-\.\/]+$`
	Path string `json:"path"`
}

// BackendStatus defines the observed state of Backend
type BackendStatus struct {
	// INSERT ADDITIONAL STATUS FIELD - define observed state of cluster
	// Important: Run "make" to regenerate code after modifying this file

	// Conditions represent the latest available observations of the Backend's state
	// +optional
	// +patchMergeKey=type
	// +patchStrategy=merge
	Conditions []metav1.Condition `json:"conditions,omitempty" patchStrategy:"merge" patchMergeKey:"type"`

	// IsAvailable indicates whether the backend is available
	// +optional
	IsAvailable bool `json:"isAvailable,omitempty"`

	// LastProbeTime is the last time the backend was probed
	// +optional
	LastProbeTime *metav1.Time `json:"lastProbeTime,omitempty"`

	// CurrentLoad represents the current load on the backend
	// +optional
	CurrentLoad int32 `json:"currentLoad,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:printcolumn:name="Type",type="string",JSONPath=".spec.type",description="Backend type"
// +kubebuilder:printcolumn:name="Endpoint",type="string",JSONPath=".spec.endpoint.url",description="Backend URL endpoint"
// +kubebuilder:printcolumn:name="Service",type="string",JSONPath=".spec.endpoint.service.objectReference.name",description="Backend Kubernetes service"
// +kubebuilder:printcolumn:name="Available",type="boolean",JSONPath=".status.isAvailable",description="Backend availability"
// +kubebuilder:printcolumn:name="Age",type="date",JSONPath=".metadata.creationTimestamp"

// Backend is the Schema for the backends API
type Backend struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   BackendSpec   `json:"spec,omitempty"`
	Status BackendStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// BackendList contains a list of Backend
type BackendList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []Backend `json:"items"`
}

func init() {
	SchemeBuilder.Register(&Backend{}, &BackendList{})
}
