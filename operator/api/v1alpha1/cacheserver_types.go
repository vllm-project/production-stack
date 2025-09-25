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
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// EDIT THIS FILE!  THIS IS SCAFFOLDING FOR YOU TO OWN!
// NOTE: json tags are required.  Any new fields you add must have json tags for the fields to be serialized.

// CacheServerSpec defines the desired state of CacheServer
type CacheServerSpec struct {
	// Image configuration for the cache server
	Image ImageSpec `json:"image"`

	// Container port for the cache server
	// +kubebuilder:default=8000
	Port int32 `json:"port"`

	// Resource requirements
	Resources ResourceRequirements `json:"resources"`

	// Number of replicas
	// +kubebuilder:default=1
	Replicas int32 `json:"replicas"`

	// Deployment strategy
	// +kubebuilder:validation:Enum=RollingUpdate;Recreate
	// +kubebuilder:default=RollingUpdate
	DeploymentStrategy string `json:"deploymentStrategy"`
}

// CacheServerStatus defines the observed state of CacheServer
type CacheServerStatus struct {
	// Last time the status was updated
	LastUpdated metav1.Time `json:"lastUpdated,omitempty"`

	// Current status of the cache server
	Status string `json:"status,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:printcolumn:name="Status",type="string",JSONPath=".status.status"
// +kubebuilder:printcolumn:name="Age",type="date",JSONPath=".metadata.creationTimestamp"

// CacheServer is the Schema for the cacheservers API
type CacheServer struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   CacheServerSpec   `json:"spec,omitempty"`
	Status CacheServerStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// CacheServerList contains a list of CacheServer
type CacheServerList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []CacheServer `json:"items"`
}

func init() {
	SchemeBuilder.Register(&CacheServer{}, &CacheServerList{})
}
