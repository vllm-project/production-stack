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

// RouteSpec defines the desired state of Route
type RouteSpec struct {
	// INSERT ADDITIONAL SPEC FIELDS - desired state of cluster
	// Important: Run "make" to regenerate code after modifying this file

	// BackendRef is a reference to the Backend resource
	// +kubebuilder:validation:Required
	BackendRef corev1.ObjectReference `json:"backendRef"`

	// Path is the URL path to match for this route
	// +kubebuilder:validation:Required
	Path string `json:"path"`

	// APISchema specifies which API schema is supported by this route
	// +kubebuilder:validation:Enum=openai;anthropic;vllm
	// +kubebuilder:default=openai
	APISchema string `json:"apiSchema"`

	// Weight is the routing weight for this route (0-100)
	// +optional
	// +kubebuilder:default=100
	// +kubebuilder:validation:Minimum=0
	// +kubebuilder:validation:Maximum=100
	Weight int32 `json:"weight,omitempty"`

	// SecretRef is a reference to a secret containing API keys for this route
	// +optional
	SecretRef *SecretReference `json:"secretRef,omitempty"`

	// SemanticCachingEnabled indicates whether semantic caching is enabled for this route
	// +optional
	// +kubebuilder:default=false
	SemanticCachingEnabled bool `json:"semanticCachingEnabled,omitempty"`

	// SemanticCachingConfig provides configuration for semantic caching
	// +optional
	SemanticCachingConfig *SemanticCachingConfig `json:"semanticCachingConfig,omitempty"`

	// ConfigMapRef is a reference to the ConfigMap to create with the dynamic config
	// +kubebuilder:validation:Required
	ConfigMapRef corev1.ObjectReference `json:"configMapRef"`

	// Timeout is the request timeout in seconds
	// +optional
	// +kubebuilder:default=300
	// +kubebuilder:validation:Minimum=1
	Timeout int32 `json:"timeout,omitempty"`

	// RateLimitPerMinute is the maximum number of requests allowed per minute
	// +optional
	// +kubebuilder:validation:Minimum=0
	RateLimitPerMinute int32 `json:"rateLimitPerMinute,omitempty"`

	// Headers are additional headers to add to the request
	// +optional
	Headers map[string]string `json:"headers,omitempty"`
}

// SecretReference defines a reference to a secret and key
type SecretReference struct {
	// Name is the name of the secret
	// +kubebuilder:validation:Required
	Name string `json:"name"`

	// Namespace is the namespace of the secret
	// +optional
	Namespace string `json:"namespace,omitempty"`

	// Key is the key in the secret to use
	// +kubebuilder:validation:Required
	Key string `json:"key"`
}

// SemanticCachingConfig defines the configuration for semantic caching
type SemanticCachingConfig struct {
	// TTL is the time-to-live for cached entries in seconds
	// +optional
	// +kubebuilder:default=3600
	// +kubebuilder:validation:Minimum=1
	TTL int32 `json:"ttl,omitempty"`

	// SimilarityThreshold is the threshold for semantic similarity (0-100)
	// +optional
	// +kubebuilder:default=95
	// +kubebuilder:validation:Minimum=0
	// +kubebuilder:validation:Maximum=100
	SimilarityThreshold int32 `json:"similarityThreshold,omitempty"`

	// MaxCacheSize is the maximum number of entries in the cache
	// +optional
	// +kubebuilder:default=1000
	// +kubebuilder:validation:Minimum=1
	MaxCacheSize int32 `json:"maxCacheSize,omitempty"`
}

// RouteStatus defines the observed state of Route
type RouteStatus struct {
	// INSERT ADDITIONAL STATUS FIELD - define observed state of cluster
	// Important: Run "make" to regenerate code after modifying this file

	// Conditions represent the latest available observations of the Route's state
	// +optional
	// +patchMergeKey=type
	// +patchStrategy=merge
	Conditions []metav1.Condition `json:"conditions,omitempty" patchStrategy:"merge" patchMergeKey:"type"`

	// IsActive indicates whether the route is active
	// +optional
	IsActive bool `json:"isActive,omitempty"`

	// LastConfiguredTime is the last time the route was configured
	// +optional
	LastConfiguredTime *metav1.Time `json:"lastConfiguredTime,omitempty"`

	// RequestCount is the number of requests processed by this route
	// +optional
	RequestCount int64 `json:"requestCount,omitempty"`

	// CacheHitRate is the cache hit rate for this route (if semantic caching is enabled)
	// +optional
	CacheHitRatePercent int32 `json:"cacheHitRatePercent,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:printcolumn:name="Backend",type="string",JSONPath=".spec.backendRef.name",description="Backend reference"
// +kubebuilder:printcolumn:name="Path",type="string",JSONPath=".spec.path",description="Route path"
// +kubebuilder:printcolumn:name="API Schema",type="string",JSONPath=".spec.apiSchema",description="API schema"
// +kubebuilder:printcolumn:name="Weight",type="integer",JSONPath=".spec.weight",description="Route weight"
// +kubebuilder:printcolumn:name="Active",type="boolean",JSONPath=".status.isActive",description="Route active status"
// +kubebuilder:printcolumn:name="Age",type="date",JSONPath=".metadata.creationTimestamp"

// Route is the Schema for the routes API
type Route struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   RouteSpec   `json:"spec,omitempty"`
	Status RouteStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// RouteList contains a list of Route
type RouteList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []Route `json:"items"`
}

func init() {
	SchemeBuilder.Register(&Route{}, &RouteList{})
}
