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

// StaticRouteSpec defines the desired state of StaticRoute
type StaticRouteSpec struct {
	// INSERT ADDITIONAL SPEC FIELDS - desired state of cluster
	// Important: Run "make" to regenerate code after modifying this file

	// ServiceDiscovery specifies the service discovery method
	// +kubebuilder:validation:Enum=static
	// +kubebuilder:default=static
	ServiceDiscovery string `json:"serviceDiscovery"`

	// RoutingLogic specifies the routing logic to use
	// +kubebuilder:validation:Enum=roundrobin;least_loaded
	// +kubebuilder:default=roundrobin
	RoutingLogic string `json:"routingLogic"`

	// StaticBackends is a comma-separated list of backend URLs
	// +kubebuilder:validation:Required
	StaticBackends string `json:"staticBackends"`

	// StaticModels is a comma-separated list of model names
	// +kubebuilder:validation:Required
	StaticModels string `json:"staticModels"`

	// RouterRef is a reference to the router service
	// +optional
	RouterRef *corev1.ObjectReference `json:"routerRef,omitempty"`

	// HealthCheck defines the health check configuration for the router
	// +optional
	HealthCheck *HealthCheckConfig `json:"healthCheck,omitempty"`

	// ConfigMapName is the name of the ConfigMap to create with the dynamic config
	// +optional
	ConfigMapName string `json:"configMapName,omitempty"`
}

// HealthCheckConfig defines the configuration for health checks
type HealthCheckConfig struct {
	// Number of seconds after which the probe times out
	// +optional
	// +kubebuilder:default=5
	// +kubebuilder:validation:Minimum=1
	TimeoutSeconds int32 `json:"timeoutSeconds,omitempty"`

	// Number of seconds between probe attempts
	// +optional
	// +kubebuilder:default=10
	// +kubebuilder:validation:Minimum=1
	PeriodSeconds int32 `json:"periodSeconds,omitempty"`

	// Minimum consecutive successes for the probe to be considered successful
	// +optional
	// +kubebuilder:default=1
	// +kubebuilder:validation:Minimum=1
	SuccessThreshold int32 `json:"successThreshold,omitempty"`

	// Minimum consecutive failures for the probe to be considered failed
	// +optional
	// +kubebuilder:default=3
	// +kubebuilder:validation:Minimum=1
	FailureThreshold int32 `json:"failureThreshold,omitempty"`
}

// StaticRouteStatus defines the observed state of StaticRoute
type StaticRouteStatus struct {
	// INSERT ADDITIONAL STATUS FIELD - define observed state of cluster
	// Important: Run "make" to regenerate code after modifying this file

	// Conditions represent the latest available observations of the StaticRoute's state
	// +optional
	// +patchMergeKey=type
	// +patchStrategy=merge
	Conditions []metav1.Condition `json:"conditions,omitempty" patchStrategy:"merge" patchMergeKey:"type"`

	// ConfigMapRef is a reference to the created ConfigMap
	// +optional
	ConfigMapRef string `json:"configMapRef,omitempty"`

	// LastAppliedTime is the last time the configuration was applied to the router
	// +optional
	LastAppliedTime *metav1.Time `json:"lastAppliedTime,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status

// StaticRoute is the Schema for the staticroutes API
type StaticRoute struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   StaticRouteSpec   `json:"spec,omitempty"`
	Status StaticRouteStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// StaticRouteList contains a list of StaticRoute
type StaticRouteList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []StaticRoute `json:"items"`
}

func init() {
	SchemeBuilder.Register(&StaticRoute{}, &StaticRouteList{})
}
