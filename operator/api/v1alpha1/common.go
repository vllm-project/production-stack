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

import "k8s.io/apimachinery/pkg/api/resource"

// ResourceRequirements defines container resource requirements.
// Flat CPU and memory fields are retained for backward compatibility and apply
// to both requests and limits unless overridden by the corresponding nested
// field. GPU and GPUType are shared by requests and limits.
type ResourceRequirements struct {
	// +kubebuilder:validation:Pattern="^$|^(\\+|-)?(([0-9]+(\\.[0-9]*)?)|(\\.[0-9]+))(([KMGTPE]i)|[numkMGTPE]|([eE](\\+|-)?(([0-9]+(\\.[0-9]*)?)|(\\.[0-9]+))))?$"
	CPU string `json:"cpu,omitempty"`
	// +kubebuilder:validation:Pattern="^$|^(\\+|-)?(([0-9]+(\\.[0-9]*)?)|(\\.[0-9]+))(([KMGTPE]i)|[numkMGTPE]|([eE](\\+|-)?(([0-9]+(\\.[0-9]*)?)|(\\.[0-9]+))))?$"
	Memory string `json:"memory,omitempty"`
	// +kubebuilder:validation:Pattern="^$|^(\\+|-)?(([0-9]+(\\.[0-9]*)?)|(\\.[0-9]+))(([KMGTPE]i)|[numkMGTPE]|([eE](\\+|-)?(([0-9]+(\\.[0-9]*)?)|(\\.[0-9]+))))?$"
	// +kubebuilder:validation:XValidation:rule="self == '' || (quantity(self).isInteger() && sign(quantity(self)) >= 0)",message="gpu must be a nonnegative integer quantity"
	GPU string `json:"gpu,omitempty"`
	// +kubebuilder:validation:Pattern="^$|^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*/[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?$"
	// +kubebuilder:validation:XValidation:rule="self == '' || (!self.startsWith('requests.') && !self.contains('kubernetes.io/'))",message="gpuType must be a third-party extended resource name"
	GPUType string `json:"gpuType,omitempty"`
	// Requests overrides flat CPU and memory values for requests.
	Requests *ResourceSpec `json:"requests,omitempty"`
	// Limits overrides flat CPU and memory values for limits.
	Limits *ResourceSpec `json:"limits,omitempty"`
}

// ResourceSpec defines CPU and memory values for either requests or limits.
type ResourceSpec struct {
	CPU    *resource.Quantity `json:"cpu,omitempty"`
	Memory *resource.Quantity `json:"memory,omitempty"`
}

// ImageSpec defines the container image configuration
type ImageSpec struct {
	Registry       string `json:"registry"`
	Name           string `json:"name"`
	PullPolicy     string `json:"pullPolicy,omitempty"`
	PullSecretName string `json:"pullSecretName,omitempty"`
}
