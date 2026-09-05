/*
Copyright 2026.

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

package controller

import (
	"fmt"
	"strings"

	corev1 "k8s.io/api/core/v1"
	apiequality "k8s.io/apimachinery/pkg/api/equality"
	"k8s.io/apimachinery/pkg/api/resource"
	"k8s.io/apimachinery/pkg/util/validation"

	productionstackv1alpha1 "production-stack/api/v1alpha1"
)

func buildResourceRequirements(
	config productionstackv1alpha1.ResourceRequirements,
) (corev1.ResourceRequirements, error) {
	gpuType := config.GPUType
	if gpuType == "" {
		gpuType = "nvidia.com/gpu"
	}
	if config.GPU != "" || config.GPUType != "" {
		if err := validateExtendedResourceName(corev1.ResourceName(gpuType)); err != nil {
			return corev1.ResourceRequirements{}, fmt.Errorf("invalid gpuType %q: %w", gpuType, err)
		}
	}

	var gpu resource.Quantity
	if config.GPU != "" {
		var err error
		gpu, err = resource.ParseQuantity(config.GPU)
		if err != nil {
			return corev1.ResourceRequirements{}, fmt.Errorf("parse gpu quantity %q: %w", config.GPU, err)
		}
		if gpu.Sign() < 0 || gpu.MilliValue()%1000 != 0 {
			return corev1.ResourceRequirements{}, fmt.Errorf("gpu quantity %q must be a nonnegative integer", config.GPU)
		}
	}

	requests, err := resolveResourceSpec(config, config.Requests)
	if err != nil {
		return corev1.ResourceRequirements{}, err
	}
	limits, err := resolveResourceSpec(config, config.Limits)
	if err != nil {
		return corev1.ResourceRequirements{}, err
	}
	if requests.CPU == nil {
		requests.CPU = limits.CPU
	}
	if requests.Memory == nil {
		requests.Memory = limits.Memory
	}
	if err := validateRequestDoesNotExceedLimit("cpu", requests.CPU, limits.CPU); err != nil {
		return corev1.ResourceRequirements{}, err
	}
	if err := validateRequestDoesNotExceedLimit("memory", requests.Memory, limits.Memory); err != nil {
		return corev1.ResourceRequirements{}, err
	}

	resources := corev1.ResourceRequirements{
		Requests: buildResourceList(requests),
		Limits:   buildResourceList(limits),
	}
	if config.GPU != "" {
		if resources.Requests == nil {
			resources.Requests = corev1.ResourceList{}
		}
		if resources.Limits == nil {
			resources.Limits = corev1.ResourceList{}
		}
		resources.Requests[corev1.ResourceName(gpuType)] = gpu
		resources.Limits[corev1.ResourceName(gpuType)] = gpu
	}
	return resources, nil
}

func validateRequestDoesNotExceedLimit(
	name string,
	request, limit *resource.Quantity,
) error {
	if request != nil && limit != nil && request.Cmp(*limit) > 0 {
		return fmt.Errorf(
			"%s request %q must not exceed limit %q",
			name,
			request.String(),
			limit.String(),
		)
	}
	return nil
}

func applySidecarResourceDefaults(
	config productionstackv1alpha1.ResourceRequirements,
) productionstackv1alpha1.ResourceRequirements {
	if config.CPU == "" {
		config.CPU = sidecarResourceDefault("0.5", resourceValue(config.Requests, true), resourceValue(config.Limits, true))
	}
	if config.Memory == "" {
		config.Memory = sidecarResourceDefault("128Mi", resourceValue(config.Requests, false), resourceValue(config.Limits, false))
	}
	if config.GPU == "" {
		config.GPU = "0"
	}
	return config
}

func resourceValue(spec *productionstackv1alpha1.ResourceSpec, cpu bool) *resource.Quantity {
	if spec == nil {
		return nil
	}
	if cpu {
		return spec.CPU
	}
	return spec.Memory
}

func sidecarResourceDefault(
	defaultValue string,
	request, limit *resource.Quantity,
) string {
	defaultQuantity := resource.MustParse(defaultValue)
	if request != nil && limit == nil && request.Cmp(defaultQuantity) > 0 {
		return request.String()
	}
	if limit != nil && request == nil && limit.Cmp(defaultQuantity) < 0 {
		return limit.String()
	}
	return defaultValue
}

// validateExtendedResourceName mirrors Kubernetes' extended-resource checks
// without importing the full k8s.io/kubernetes module.
func validateExtendedResourceName(name corev1.ResourceName) error {
	value := string(name)
	if !strings.Contains(value, "/") || strings.Contains(value, corev1.ResourceDefaultNamespacePrefix) {
		return fmt.Errorf("must be a third-party extended resource name")
	}
	if strings.HasPrefix(value, corev1.DefaultResourceRequestsPrefix) {
		return fmt.Errorf("must not use the %q quota prefix", corev1.DefaultResourceRequestsPrefix)
	}
	nameForQuota := corev1.DefaultResourceRequestsPrefix + value
	if errs := validation.IsQualifiedName(nameForQuota); len(errs) != 0 {
		return fmt.Errorf("must be a qualified resource name: %s", strings.Join(errs, "; "))
	}
	return nil
}

func resolveResourceSpec(
	legacy productionstackv1alpha1.ResourceRequirements,
	explicit *productionstackv1alpha1.ResourceSpec,
) (productionstackv1alpha1.ResourceSpec, error) {
	resolved := productionstackv1alpha1.ResourceSpec{}
	if legacy.CPU != "" {
		cpu, err := resource.ParseQuantity(legacy.CPU)
		if err != nil {
			return productionstackv1alpha1.ResourceSpec{}, fmt.Errorf("parse cpu quantity %q: %w", legacy.CPU, err)
		}
		resolved.CPU = &cpu
	}
	if legacy.Memory != "" {
		memory, err := resource.ParseQuantity(legacy.Memory)
		if err != nil {
			return productionstackv1alpha1.ResourceSpec{}, fmt.Errorf("parse memory quantity %q: %w", legacy.Memory, err)
		}
		resolved.Memory = &memory
	}
	if explicit == nil {
		return resolved, nil
	}
	if explicit.CPU != nil {
		resolved.CPU = explicit.CPU
	}
	if explicit.Memory != nil {
		resolved.Memory = explicit.Memory
	}
	return resolved, nil
}

func buildResourceList(config productionstackv1alpha1.ResourceSpec) corev1.ResourceList {
	if config.CPU == nil && config.Memory == nil {
		return nil
	}
	resources := corev1.ResourceList{}
	if config.CPU != nil {
		resources[corev1.ResourceCPU] = config.CPU.DeepCopy()
	}
	if config.Memory != nil {
		resources[corev1.ResourceMemory] = config.Memory.DeepCopy()
	}
	return resources
}

func resourceRequirementsEqual(expected, actual corev1.ResourceRequirements) bool {
	return apiequality.Semantic.DeepEqual(expected, actual)
}

func containerResourceRequirementsEqual(
	expected, actual map[string]corev1.ResourceRequirements,
) bool {
	if len(expected) != len(actual) {
		return false
	}
	for name, expectedResources := range expected {
		actualResources, ok := actual[name]
		if !ok || !resourceRequirementsEqual(expectedResources, actualResources) {
			return false
		}
	}
	return true
}
