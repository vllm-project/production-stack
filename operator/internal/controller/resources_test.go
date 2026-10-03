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
	"context"
	"encoding/json"
	"strings"
	"testing"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	rbacv1 "k8s.io/api/rbac/v1"
	apiequality "k8s.io/apimachinery/pkg/api/equality"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	productionstackv1alpha1 "production-stack/api/v1alpha1"
)

func TestResourceRequirementsRejectInvalidNestedQuantities(t *testing.T) {
	tests := map[string]string{
		"request CPU":    `{"requests":{"cpu":"not-a-quantity"}}`,
		"request memory": `{"requests":{"memory":"not-a-quantity"}}`,
		"limit CPU":      `{"limits":{"cpu":"not-a-quantity"}}`,
		"limit memory":   `{"limits":{"memory":"not-a-quantity"}}`,
	}
	for name, value := range tests {
		t.Run(name, func(t *testing.T) {
			var resources productionstackv1alpha1.ResourceRequirements
			if err := json.Unmarshal([]byte(value), &resources); err == nil {
				t.Fatal("expected invalid nested resource quantity to be rejected")
			}
		})
	}
}

func TestBuildResourceRequirementsRejectsInvalidFlatQuantities(t *testing.T) {
	tests := map[string]productionstackv1alpha1.ResourceRequirements{
		"cpu":    {CPU: "not-a-quantity"},
		"memory": {Memory: "not-a-quantity"},
		"gpu":    {GPU: "not-a-quantity"},
	}
	for field, resources := range tests {
		t.Run(field, func(t *testing.T) {
			_, err := buildResourceRequirements(resources)
			if err == nil {
				t.Fatalf("expected invalid flat %s quantity to return an error", field)
			}
			if !strings.Contains(err.Error(), field) {
				t.Fatalf("expected error %q to identify %s", err, field)
			}
		})
	}
}

func TestBuildResourceRequirementsRejectsInvalidExtendedGPUResources(t *testing.T) {
	tests := map[string]productionstackv1alpha1.ResourceRequirements{
		"fractional quantity":       {GPU: "500m"},
		"negative quantity":         {GPU: "-1"},
		"CPU name collision":        {GPU: "1", GPUType: "cpu"},
		"memory name collision":     {GPU: "1", GPUType: "memory"},
		"malformed resource name":   {GPU: "1", GPUType: "example.com/gpu/extra"},
		"unqualified resource name": {GPU: "1", GPUType: "gpu"},
		"resource name without GPU": {GPUType: "cpu"},
		"native resource name":      {GPU: "1", GPUType: "kubernetes.io/gpu"},
		"quota resource name":       {GPU: "1", GPUType: "requests.example.com/gpu"},
	}
	for name, resources := range tests {
		t.Run(name, func(t *testing.T) {
			if _, err := buildResourceRequirements(resources); err == nil {
				t.Fatal("expected invalid extended GPU resource to return an error")
			}
		})
	}
}

func TestBuildResourceRequirementsAcceptsExtendedGPUResources(t *testing.T) {
	tests := map[string]struct {
		resources productionstackv1alpha1.ResourceRequirements
		name      corev1.ResourceName
		quantity  resource.Quantity
	}{
		"default NVIDIA resource": {
			resources: productionstackv1alpha1.ResourceRequirements{GPU: "1"},
			name:      "nvidia.com/gpu",
			quantity:  resource.MustParse("1"),
		},
		"custom qualified resource": {
			resources: productionstackv1alpha1.ResourceRequirements{GPU: "2", GPUType: "accelerator.example.com/gpu"},
			name:      "accelerator.example.com/gpu",
			quantity:  resource.MustParse("2"),
		},
		"semantically integral quantity": {
			resources: productionstackv1alpha1.ResourceRequirements{GPU: "1000m", GPUType: "accelerator.example.com/gpu"},
			name:      "accelerator.example.com/gpu",
			quantity:  resource.MustParse("1000m"),
		},
	}
	for name, test := range tests {
		t.Run(name, func(t *testing.T) {
			got := mustBuildResourceRequirements(t, test.resources)
			request := got.Requests[test.name]
			if !request.Equal(test.quantity) {
				t.Fatalf("request quantity = %s, want %s", request.String(), test.quantity.String())
			}
			limit := got.Limits[test.name]
			if !limit.Equal(test.quantity) {
				t.Fatalf("limit quantity = %s, want %s", limit.String(), test.quantity.String())
			}
		})
	}
}

func TestControllerBuildersRejectInvalidResources(t *testing.T) {
	scheme := resourceTestScheme(t)
	builders := map[string]func(productionstackv1alpha1.ResourceRequirements) error{
		"CacheServer": func(resources productionstackv1alpha1.ResourceRequirements) error {
			cacheServer := &productionstackv1alpha1.CacheServer{}
			cacheServer.Spec.Resources = resources
			_, err := (&CacheServerReconciler{Scheme: scheme}).deploymentForCacheServer(cacheServer)
			return err
		},
		"VLLMRouter": func(resources productionstackv1alpha1.ResourceRequirements) error {
			router := &productionstackv1alpha1.VLLMRouter{}
			router.Spec.Resources = resources
			_, err := (&VLLMRouterReconciler{Scheme: scheme}).deploymentForVLLMRouter(router)
			return err
		},
		"VLLMRuntime": func(resources productionstackv1alpha1.ResourceRequirements) error {
			runtimeResource := &productionstackv1alpha1.VLLMRuntime{}
			runtimeResource.Spec.DeploymentConfig.Resources = resources
			_, err := (&VLLMRuntimeReconciler{Scheme: scheme}).deploymentForVLLMRuntime(runtimeResource)
			return err
		},
		"VLLMRuntime sidecar": func(resources productionstackv1alpha1.ResourceRequirements) error {
			runtimeResource := &productionstackv1alpha1.VLLMRuntime{}
			runtimeResource.Spec.DeploymentConfig.SidecarConfig.Resources = resources
			_, err := (&VLLMRuntimeReconciler{Scheme: scheme}).buildSidecarContainer(runtimeResource)
			return err
		},
	}
	invalid := map[string]productionstackv1alpha1.ResourceRequirements{
		"fractional quantity":       {GPU: "500m"},
		"negative quantity":         {GPU: "-1"},
		"CPU name collision":        {GPU: "1", GPUType: "cpu"},
		"memory name collision":     {GPU: "1", GPUType: "memory"},
		"malformed resource name":   {GPU: "1", GPUType: "example.com/gpu/extra"},
		"unqualified resource name": {GPU: "1", GPUType: "gpu"},
		"resource name without GPU": {GPUType: "cpu"},
		"CPU request above limit": {
			Requests: &productionstackv1alpha1.ResourceSpec{CPU: quantityPtr("1")},
			Limits:   &productionstackv1alpha1.ResourceSpec{CPU: quantityPtr("500m")},
		},
		"memory request above limit": {
			Requests: &productionstackv1alpha1.ResourceSpec{Memory: quantityPtr("1Gi")},
			Limits:   &productionstackv1alpha1.ResourceSpec{Memory: quantityPtr("512Mi")},
		},
	}
	for builderName, build := range builders {
		for invalidName, resources := range invalid {
			t.Run(builderName+"/"+invalidName, func(t *testing.T) {
				if err := build(resources); err == nil {
					t.Fatal("expected builder to reject invalid resources")
				}
			})
		}
	}
}

func TestControllerBuildersRejectInvalidFlatQuantities(t *testing.T) {
	scheme := runtime.NewScheme()
	if err := productionstackv1alpha1.AddToScheme(scheme); err != nil {
		t.Fatalf("add API types to scheme: %v", err)
	}

	tests := map[string]func() error{
		"CacheServer": func() error {
			cacheServer := &productionstackv1alpha1.CacheServer{}
			cacheServer.Spec.Resources.GPU = "not-a-quantity"
			_, err := (&CacheServerReconciler{Scheme: scheme}).deploymentForCacheServer(cacheServer)
			return err
		},
		"VLLMRouter": func() error {
			router := &productionstackv1alpha1.VLLMRouter{}
			router.Spec.Resources.GPU = "not-a-quantity"
			_, err := (&VLLMRouterReconciler{Scheme: scheme}).deploymentForVLLMRouter(router)
			return err
		},
		"VLLMRuntime": func() error {
			runtimeResource := &productionstackv1alpha1.VLLMRuntime{}
			runtimeResource.Spec.DeploymentConfig.Resources.GPU = "not-a-quantity"
			_, err := (&VLLMRuntimeReconciler{Scheme: scheme}).deploymentForVLLMRuntime(runtimeResource)
			return err
		},
		"VLLMRuntime sidecar": func() error {
			runtimeResource := &productionstackv1alpha1.VLLMRuntime{}
			runtimeResource.Spec.DeploymentConfig.SidecarConfig.Resources.GPU = "not-a-quantity"
			_, err := (&VLLMRuntimeReconciler{Scheme: scheme}).buildSidecarContainer(runtimeResource)
			return err
		},
	}
	for name, build := range tests {
		t.Run(name, func(t *testing.T) {
			if err := build(); err == nil {
				t.Fatal("expected invalid in-memory resource quantity to return an error")
			}
		})
	}
}

func TestReconcilersValidateResourcesBeforeMutating(t *testing.T) {
	invalid := map[string]productionstackv1alpha1.ResourceRequirements{
		"fractional quantity":       {GPU: "500m"},
		"negative quantity":         {GPU: "-1"},
		"CPU name collision":        {GPU: "1", GPUType: "cpu"},
		"memory name collision":     {GPU: "1", GPUType: "memory"},
		"malformed resource name":   {GPU: "1", GPUType: "example.com/gpu/extra"},
		"unqualified resource name": {GPU: "1", GPUType: "gpu"},
		"resource name without GPU": {GPUType: "cpu"},
		"CPU request above limit": {
			Requests: &productionstackv1alpha1.ResourceSpec{CPU: quantityPtr("1")},
			Limits:   &productionstackv1alpha1.ResourceSpec{CPU: quantityPtr("500m")},
		},
		"memory request above limit": {
			Requests: &productionstackv1alpha1.ResourceSpec{Memory: quantityPtr("1Gi")},
			Limits:   &productionstackv1alpha1.ResourceSpec{Memory: quantityPtr("512Mi")},
		},
	}

	type reconcileCase struct {
		object    client.Object
		reconcile func(client.Client) error
	}
	for invalidName, resources := range invalid {
		resources := resources
		cases := map[string]reconcileCase{
			"CacheServer": {
				object: &productionstackv1alpha1.CacheServer{
					ObjectMeta: metav1.ObjectMeta{Name: "test", Namespace: "default"},
					Spec:       productionstackv1alpha1.CacheServerSpec{Resources: resources},
				},
				reconcile: func(k8sClient client.Client) error {
					_, err := (&CacheServerReconciler{Client: k8sClient, Scheme: k8sClient.Scheme()}).Reconcile(
						context.Background(), ctrl.Request{NamespacedName: types.NamespacedName{Name: "test", Namespace: "default"}},
					)
					return err
				},
			},
			"VLLMRouter": {
				object: &productionstackv1alpha1.VLLMRouter{
					ObjectMeta: metav1.ObjectMeta{Name: "test", Namespace: "default"},
					Spec:       productionstackv1alpha1.VLLMRouterSpec{Resources: resources},
				},
				reconcile: func(k8sClient client.Client) error {
					_, err := (&VLLMRouterReconciler{Client: k8sClient, Scheme: k8sClient.Scheme()}).Reconcile(
						context.Background(), ctrl.Request{NamespacedName: types.NamespacedName{Name: "test", Namespace: "default"}},
					)
					return err
				},
			},
			"VLLMRuntime": {
				object: &productionstackv1alpha1.VLLMRuntime{
					ObjectMeta: metav1.ObjectMeta{Name: "test", Namespace: "default"},
					Spec: productionstackv1alpha1.VLLMRuntimeSpec{DeploymentConfig: productionstackv1alpha1.DeploymentConfig{
						Resources: resources,
					}},
				},
				reconcile: func(k8sClient client.Client) error {
					_, err := (&VLLMRuntimeReconciler{Client: k8sClient, Scheme: k8sClient.Scheme()}).Reconcile(
						context.Background(), ctrl.Request{NamespacedName: types.NamespacedName{Name: "test", Namespace: "default"}},
					)
					return err
				},
			},
			"VLLMRuntime sidecar": {
				object: &productionstackv1alpha1.VLLMRuntime{
					ObjectMeta: metav1.ObjectMeta{Name: "test", Namespace: "default"},
					Spec: productionstackv1alpha1.VLLMRuntimeSpec{DeploymentConfig: productionstackv1alpha1.DeploymentConfig{
						SidecarConfig: productionstackv1alpha1.SidecarConfig{Enabled: true, Resources: resources},
					}},
				},
				reconcile: func(k8sClient client.Client) error {
					_, err := (&VLLMRuntimeReconciler{Client: k8sClient, Scheme: k8sClient.Scheme()}).Reconcile(
						context.Background(), ctrl.Request{NamespacedName: types.NamespacedName{Name: "test", Namespace: "default"}},
					)
					return err
				},
			},
		}
		for controllerName, test := range cases {
			t.Run(controllerName+"/"+invalidName, func(t *testing.T) {
				scheme := resourceTestScheme(t)
				baseClient := fake.NewClientBuilder().WithScheme(scheme).WithObjects(test.object).Build()
				recordingClient := &mutationCountingClient{Client: baseClient}
				if err := test.reconcile(recordingClient); err == nil {
					t.Fatal("expected reconcile to reject invalid resources")
				}
				if recordingClient.mutations != 0 {
					t.Fatalf("reconcile performed %d mutations before validating resources", recordingClient.mutations)
				}
			})
		}
	}
}

func TestControllersBuildResourceRequestsAndLimits(t *testing.T) {
	resources := decodeResourceRequirements(t, `{
		"cpu": "1",
		"memory": "1Gi",
		"gpu": "1",
		"gpuType": "legacy.example/gpu",
		"requests": {
			"cpu": "250m"
		},
		"limits": {
			"memory": "2Gi"
		}
	}`)
	want := corev1.ResourceRequirements{
		Requests: corev1.ResourceList{
			corev1.ResourceCPU:                        resource.MustParse("250m"),
			corev1.ResourceMemory:                     resource.MustParse("1Gi"),
			corev1.ResourceName("legacy.example/gpu"): resource.MustParse("1"),
		},
		Limits: corev1.ResourceList{
			corev1.ResourceCPU:                        resource.MustParse("1"),
			corev1.ResourceMemory:                     resource.MustParse("2Gi"),
			corev1.ResourceName("legacy.example/gpu"): resource.MustParse("1"),
		},
	}

	scheme := runtime.NewScheme()
	if err := productionstackv1alpha1.AddToScheme(scheme); err != nil {
		t.Fatalf("add API types to scheme: %v", err)
	}

	t.Run("VLLMRuntime", func(t *testing.T) {
		runtimeResource := &productionstackv1alpha1.VLLMRuntime{}
		runtimeResource.Spec.DeploymentConfig.Resources = resources
		reconciler := &VLLMRuntimeReconciler{Scheme: scheme}
		deployment := mustBuildVLLMRuntimeDeployment(t, reconciler, runtimeResource)
		assertResourceRequirements(t, deployment.Spec.Template.Spec.Containers[0].Resources, want)
	})

	t.Run("VLLMRuntime sidecar", func(t *testing.T) {
		runtimeResource := &productionstackv1alpha1.VLLMRuntime{}
		runtimeResource.Spec.DeploymentConfig.SidecarConfig.Resources = resources
		reconciler := &VLLMRuntimeReconciler{Scheme: scheme}
		container := mustBuildVLLMRuntimeSidecar(t, reconciler, runtimeResource)
		assertResourceRequirements(t, container.Resources, want)
	})

	t.Run("VLLMRouter", func(t *testing.T) {
		router := &productionstackv1alpha1.VLLMRouter{}
		router.Spec.Resources = resources
		reconciler := &VLLMRouterReconciler{Scheme: scheme}
		deployment := mustBuildVLLMRouterDeployment(t, reconciler, router)
		assertResourceRequirements(t, deployment.Spec.Template.Spec.Containers[0].Resources, want)
	})

	t.Run("CacheServer", func(t *testing.T) {
		cacheServer := &productionstackv1alpha1.CacheServer{}
		cacheServer.Spec.Resources = resources
		reconciler := &CacheServerReconciler{Scheme: scheme}
		deployment := mustBuildCacheServerDeployment(t, reconciler, cacheServer)
		assertResourceRequirements(t, deployment.Spec.Template.Spec.Containers[0].Resources, want)
	})
}

func TestBuildResourceRequirementsPreservesNilLimitsForRequestOnlyConfig(t *testing.T) {
	resources := productionstackv1alpha1.ResourceRequirements{
		Requests: &productionstackv1alpha1.ResourceSpec{CPU: quantityPtr("500m")},
	}

	got := mustBuildResourceRequirements(t, resources)
	if got.Requests == nil {
		t.Fatal("expected requests to remain non-nil")
	}
	if got.Limits != nil {
		t.Fatalf("expected absent limits to remain nil, got %#v", got.Limits)
	}

	encoded, err := json.Marshal(got)
	if err != nil {
		t.Fatalf("marshal request-only resources: %v", err)
	}
	var roundTripped corev1.ResourceRequirements
	if err := json.Unmarshal(encoded, &roundTripped); err != nil {
		t.Fatalf("unmarshal request-only resources: %v", err)
	}
	assertResourceRequirements(t, roundTripped, got)
}

func TestBuildResourceRequirementsRejectsRequestsAboveLimits(t *testing.T) {
	tests := map[string]productionstackv1alpha1.ResourceRequirements{
		"explicit CPU": {
			Requests: &productionstackv1alpha1.ResourceSpec{CPU: quantityPtr("1")},
			Limits:   &productionstackv1alpha1.ResourceSpec{CPU: quantityPtr("500m")},
		},
		"explicit memory": {
			Requests: &productionstackv1alpha1.ResourceSpec{Memory: quantityPtr("1Gi")},
			Limits:   &productionstackv1alpha1.ResourceSpec{Memory: quantityPtr("512Mi")},
		},
		"request over flat CPU": {
			CPU:      "500m",
			Requests: &productionstackv1alpha1.ResourceSpec{CPU: quantityPtr("1")},
		},
		"flat memory over limit": {
			Memory: "1Gi",
			Limits: &productionstackv1alpha1.ResourceSpec{Memory: quantityPtr("512Mi")},
		},
	}

	for name, resources := range tests {
		t.Run(name, func(t *testing.T) {
			if _, err := buildResourceRequirements(resources); err == nil {
				t.Fatal("expected a request above its limit to return an error")
			}
		})
	}
}

func TestControllersDefaultMissingRequestsFromLimits(t *testing.T) {
	resources := productionstackv1alpha1.ResourceRequirements{
		Limits: &productionstackv1alpha1.ResourceSpec{
			CPU:    quantityPtr("2"),
			Memory: quantityPtr("2Gi"),
		},
	}
	want := corev1.ResourceRequirements{
		Requests: corev1.ResourceList{
			corev1.ResourceCPU:    resource.MustParse("2"),
			corev1.ResourceMemory: resource.MustParse("2Gi"),
		},
		Limits: corev1.ResourceList{
			corev1.ResourceCPU:    resource.MustParse("2"),
			corev1.ResourceMemory: resource.MustParse("2Gi"),
		},
	}

	assertResourceRequirements(t, mustBuildResourceRequirements(t, resources), want)
}

func TestVLLMRuntimeSidecarKeepsDefaultsWithLimitsOnly(t *testing.T) {
	runtimeResource := &productionstackv1alpha1.VLLMRuntime{}
	runtimeResource.Spec.DeploymentConfig.SidecarConfig.Resources.Limits =
		&productionstackv1alpha1.ResourceSpec{
			CPU:    quantityPtr("2"),
			Memory: quantityPtr("2Gi"),
		}

	container := mustBuildVLLMRuntimeSidecar(t, &VLLMRuntimeReconciler{}, runtimeResource)
	want := corev1.ResourceRequirements{
		Requests: corev1.ResourceList{
			corev1.ResourceCPU:                    resource.MustParse("0.5"),
			corev1.ResourceMemory:                 resource.MustParse("128Mi"),
			corev1.ResourceName("nvidia.com/gpu"): resource.MustParse("0"),
		},
		Limits: corev1.ResourceList{
			corev1.ResourceCPU:                    resource.MustParse("2"),
			corev1.ResourceMemory:                 resource.MustParse("2Gi"),
			corev1.ResourceName("nvidia.com/gpu"): resource.MustParse("0"),
		},
	}

	assertResourceRequirements(t, container.Resources, want)
}

func TestVLLMRuntimeSidecarAdjustsGeneratedDefaultsAroundExplicitValues(t *testing.T) {
	tests := map[string]struct {
		resources productionstackv1alpha1.ResourceRequirements
		want      corev1.ResourceRequirements
	}{
		"CPU request above default": {
			resources: productionstackv1alpha1.ResourceRequirements{
				Requests: &productionstackv1alpha1.ResourceSpec{CPU: quantityPtr("1")},
			},
			want: sidecarResourceRequirements("1", "1", "128Mi", "128Mi"),
		},
		"memory request above default": {
			resources: productionstackv1alpha1.ResourceRequirements{
				Requests: &productionstackv1alpha1.ResourceSpec{Memory: quantityPtr("256Mi")},
			},
			want: sidecarResourceRequirements("0.5", "0.5", "256Mi", "256Mi"),
		},
		"CPU limit below default": {
			resources: productionstackv1alpha1.ResourceRequirements{
				Limits: &productionstackv1alpha1.ResourceSpec{CPU: quantityPtr("250m")},
			},
			want: sidecarResourceRequirements("250m", "250m", "128Mi", "128Mi"),
		},
		"memory limit below default": {
			resources: productionstackv1alpha1.ResourceRequirements{
				Limits: &productionstackv1alpha1.ResourceSpec{Memory: quantityPtr("64Mi")},
			},
			want: sidecarResourceRequirements("0.5", "0.5", "64Mi", "64Mi"),
		},
	}

	for name, test := range tests {
		t.Run(name, func(t *testing.T) {
			runtimeResource := &productionstackv1alpha1.VLLMRuntime{}
			runtimeResource.Spec.DeploymentConfig.SidecarConfig.Resources = test.resources

			container := mustBuildVLLMRuntimeSidecar(t, &VLLMRuntimeReconciler{}, runtimeResource)
			assertResourceRequirements(t, container.Resources, test.want)
		})
	}
}

func TestControllersKeepGPURequestsAndLimitsEqual(t *testing.T) {
	resources := decodeResourceRequirements(t, `{
		"gpu": "1",
		"gpuType": "legacy.example/gpu",
		"requests": {
			"gpu": "2"
		},
		"limits": {
			"gpu": "3"
		}
	}`)
	want := corev1.ResourceRequirements{
		Requests: corev1.ResourceList{
			corev1.ResourceName("legacy.example/gpu"): resource.MustParse("1"),
		},
		Limits: corev1.ResourceList{
			corev1.ResourceName("legacy.example/gpu"): resource.MustParse("1"),
		},
	}

	assertResourceRequirements(t, mustBuildResourceRequirements(t, resources), want)
}

func TestControllersPreserveFlatResourceRequirements(t *testing.T) {
	resources := decodeResourceRequirements(t, `{
		"cpu": "500m",
		"memory": "512Mi",
		"gpu": "1",
		"gpuType": "legacy.example/gpu"
	}`)
	want := corev1.ResourceRequirements{
		Requests: corev1.ResourceList{
			corev1.ResourceCPU:                        resource.MustParse("500m"),
			corev1.ResourceMemory:                     resource.MustParse("512Mi"),
			corev1.ResourceName("legacy.example/gpu"): resource.MustParse("1"),
		},
		Limits: corev1.ResourceList{
			corev1.ResourceCPU:                        resource.MustParse("500m"),
			corev1.ResourceMemory:                     resource.MustParse("512Mi"),
			corev1.ResourceName("legacy.example/gpu"): resource.MustParse("1"),
		},
	}

	scheme := runtime.NewScheme()
	if err := productionstackv1alpha1.AddToScheme(scheme); err != nil {
		t.Fatalf("add API types to scheme: %v", err)
	}

	controllers := map[string]func() corev1.ResourceRequirements{
		"VLLMRuntime": func() corev1.ResourceRequirements {
			runtimeResource := &productionstackv1alpha1.VLLMRuntime{}
			runtimeResource.Spec.DeploymentConfig.Resources = resources
			deployment := mustBuildVLLMRuntimeDeployment(t, &VLLMRuntimeReconciler{Scheme: scheme}, runtimeResource)
			return deployment.Spec.Template.Spec.Containers[0].Resources
		},
		"VLLMRouter": func() corev1.ResourceRequirements {
			router := &productionstackv1alpha1.VLLMRouter{}
			router.Spec.Resources = resources
			deployment := mustBuildVLLMRouterDeployment(t, &VLLMRouterReconciler{Scheme: scheme}, router)
			return deployment.Spec.Template.Spec.Containers[0].Resources
		},
		"CacheServer": func() corev1.ResourceRequirements {
			cacheServer := &productionstackv1alpha1.CacheServer{}
			cacheServer.Spec.Resources = resources
			deployment := mustBuildCacheServerDeployment(t, &CacheServerReconciler{Scheme: scheme}, cacheServer)
			return deployment.Spec.Template.Spec.Containers[0].Resources
		},
	}

	for name, build := range controllers {
		t.Run(name, func(t *testing.T) {
			assertResourceRequirements(t, build(), want)
		})
	}
}

func TestControllersIgnoreCanonicalEquivalentResourceQuantities(t *testing.T) {
	scheme := runtime.NewScheme()
	if err := productionstackv1alpha1.AddToScheme(scheme); err != nil {
		t.Fatalf("add API types to scheme: %v", err)
	}
	resources := productionstackv1alpha1.ResourceRequirements{
		Requests: &productionstackv1alpha1.ResourceSpec{CPU: quantityPtr("0.5")},
	}

	t.Run("CacheServer", func(t *testing.T) {
		cacheServer := &productionstackv1alpha1.CacheServer{}
		cacheServer.Spec.Resources = resources
		reconciler := &CacheServerReconciler{Scheme: scheme}
		deployment := mustBuildCacheServerDeployment(t, reconciler, cacheServer)
		deployment.Spec.Template.Spec.Containers[0].Resources.Requests[corev1.ResourceCPU] = resource.MustParse("500m")

		if mustCacheServerDeploymentNeedsUpdate(t, reconciler, deployment, cacheServer) {
			t.Fatal("canonical-equivalent CacheServer resources should not require an update")
		}
	})

	t.Run("VLLMRouter", func(t *testing.T) {
		router := &productionstackv1alpha1.VLLMRouter{}
		router.Spec.Resources = resources
		reconciler := &VLLMRouterReconciler{Scheme: scheme}
		deployment := mustBuildVLLMRouterDeployment(t, reconciler, router)
		deployment.Spec.Template.Spec.Containers[0].Resources.Requests[corev1.ResourceCPU] = resource.MustParse("500m")

		if mustVLLMRouterDeploymentNeedsUpdate(t, reconciler, deployment, router) {
			t.Fatal("canonical-equivalent VLLMRouter resources should not require an update")
		}
	})

	t.Run("VLLMRuntime", func(t *testing.T) {
		runtimeResource := &productionstackv1alpha1.VLLMRuntime{}
		runtimeResource.Spec.DeploymentConfig.NodeSelectorTerms = []corev1.NodeSelectorTerm{{}}
		runtimeResource.Spec.DeploymentConfig.Resources = resources
		reconciler := &VLLMRuntimeReconciler{Scheme: scheme}
		deployment := mustBuildVLLMRuntimeDeployment(t, reconciler, runtimeResource)
		deployment.Spec.Template.Spec.Containers[0].Resources.Requests[corev1.ResourceCPU] = resource.MustParse("500m")

		if mustVLLMRuntimeDeploymentNeedsUpdate(t, reconciler, deployment, runtimeResource) {
			t.Fatal("canonical-equivalent VLLMRuntime resources should not require an update")
		}
	})

	t.Run("VLLMRuntime sidecar", func(t *testing.T) {
		runtimeResource := &productionstackv1alpha1.VLLMRuntime{}
		runtimeResource.Spec.DeploymentConfig.NodeSelectorTerms = []corev1.NodeSelectorTerm{{}}
		runtimeResource.Spec.DeploymentConfig.SidecarConfig.Enabled = true
		runtimeResource.Spec.DeploymentConfig.SidecarConfig.Name = "sidecar"
		reconciler := &VLLMRuntimeReconciler{Scheme: scheme}
		deployment := mustBuildVLLMRuntimeDeployment(t, reconciler, runtimeResource)
		deployment.Spec.Template.Spec.Containers[1].Resources.Requests[corev1.ResourceCPU] = resource.MustParse("500m")

		if mustVLLMRuntimeDeploymentNeedsUpdate(t, reconciler, deployment, runtimeResource) {
			t.Fatal("canonical-equivalent VLLMRuntime sidecar resources should not require an update")
		}
	})
}

func TestVLLMRuntimeDeploymentNeedsUpdateForSidecarResources(t *testing.T) {
	scheme := runtime.NewScheme()
	if err := productionstackv1alpha1.AddToScheme(scheme); err != nil {
		t.Fatalf("add API types to scheme: %v", err)
	}

	runtimeResource := &productionstackv1alpha1.VLLMRuntime{}
	runtimeResource.Spec.DeploymentConfig.NodeSelectorTerms = []corev1.NodeSelectorTerm{{}}
	runtimeResource.Spec.DeploymentConfig.SidecarConfig.Enabled = true
	runtimeResource.Spec.DeploymentConfig.SidecarConfig.Name = "sidecar"
	reconciler := &VLLMRuntimeReconciler{Scheme: scheme}
	deployment := mustBuildVLLMRuntimeDeployment(t, reconciler, runtimeResource)
	if len(deployment.Spec.Template.Spec.Containers) != 2 {
		t.Fatalf("expected main container and sidecar, got %d containers", len(deployment.Spec.Template.Spec.Containers))
	}
	deployment.Spec.Template.Spec.Containers[1].Resources.Requests[corev1.ResourceCPU] = resource.MustParse("250m")

	if !mustVLLMRuntimeDeploymentNeedsUpdate(t, reconciler, deployment, runtimeResource) {
		t.Fatal("expected sidecar resource drift to require a deployment update")
	}
}

func mustBuildResourceRequirements(
	t *testing.T,
	resources productionstackv1alpha1.ResourceRequirements,
) corev1.ResourceRequirements {
	t.Helper()
	built, err := buildResourceRequirements(resources)
	if err != nil {
		t.Fatalf("build resource requirements: %v", err)
	}
	return built
}

func mustBuildCacheServerDeployment(
	t *testing.T,
	reconciler *CacheServerReconciler,
	cacheServer *productionstackv1alpha1.CacheServer,
) *appsv1.Deployment {
	t.Helper()
	deployment, err := reconciler.deploymentForCacheServer(cacheServer)
	if err != nil {
		t.Fatalf("build CacheServer deployment: %v", err)
	}
	return deployment
}

func mustBuildVLLMRouterDeployment(
	t *testing.T,
	reconciler *VLLMRouterReconciler,
	router *productionstackv1alpha1.VLLMRouter,
) *appsv1.Deployment {
	t.Helper()
	deployment, err := reconciler.deploymentForVLLMRouter(router)
	if err != nil {
		t.Fatalf("build VLLMRouter deployment: %v", err)
	}
	return deployment
}

func mustBuildVLLMRuntimeDeployment(
	t *testing.T,
	reconciler *VLLMRuntimeReconciler,
	runtimeResource *productionstackv1alpha1.VLLMRuntime,
) *appsv1.Deployment {
	t.Helper()
	deployment, err := reconciler.deploymentForVLLMRuntime(runtimeResource)
	if err != nil {
		t.Fatalf("build VLLMRuntime deployment: %v", err)
	}
	return deployment
}

func mustBuildVLLMRuntimeSidecar(
	t *testing.T,
	reconciler *VLLMRuntimeReconciler,
	runtimeResource *productionstackv1alpha1.VLLMRuntime,
) corev1.Container {
	t.Helper()
	container, err := reconciler.buildSidecarContainer(runtimeResource)
	if err != nil {
		t.Fatalf("build VLLMRuntime sidecar: %v", err)
	}
	return container
}

func mustCacheServerDeploymentNeedsUpdate(
	t *testing.T,
	reconciler *CacheServerReconciler,
	deployment *appsv1.Deployment,
	cacheServer *productionstackv1alpha1.CacheServer,
) bool {
	t.Helper()
	needsUpdate, err := reconciler.deploymentNeedsUpdate(deployment, cacheServer)
	if err != nil {
		t.Fatalf("compare CacheServer deployment: %v", err)
	}
	return needsUpdate
}

func mustVLLMRouterDeploymentNeedsUpdate(
	t *testing.T,
	reconciler *VLLMRouterReconciler,
	deployment *appsv1.Deployment,
	router *productionstackv1alpha1.VLLMRouter,
) bool {
	t.Helper()
	needsUpdate, err := reconciler.deploymentNeedsUpdate(deployment, router)
	if err != nil {
		t.Fatalf("compare VLLMRouter deployment: %v", err)
	}
	return needsUpdate
}

func mustVLLMRuntimeDeploymentNeedsUpdate(
	t *testing.T,
	reconciler *VLLMRuntimeReconciler,
	deployment *appsv1.Deployment,
	runtimeResource *productionstackv1alpha1.VLLMRuntime,
) bool {
	t.Helper()
	needsUpdate, err := reconciler.deploymentNeedsUpdate(context.Background(), deployment, runtimeResource)
	if err != nil {
		t.Fatalf("compare VLLMRuntime deployment: %v", err)
	}
	return needsUpdate
}

func decodeResourceRequirements(t *testing.T, value string) productionstackv1alpha1.ResourceRequirements {
	t.Helper()
	var resources productionstackv1alpha1.ResourceRequirements
	if err := json.Unmarshal([]byte(value), &resources); err != nil {
		t.Fatalf("decode resource requirements: %v", err)
	}
	return resources
}

func assertResourceRequirements(t *testing.T, got, want corev1.ResourceRequirements) {
	t.Helper()
	if !apiequality.Semantic.DeepEqual(got, want) {
		t.Fatalf("resource requirements mismatch\ngot:  %#v\nwant: %#v", got, want)
	}
}

func quantityPtr(value string) *resource.Quantity {
	quantity := resource.MustParse(value)
	return &quantity
}

func sidecarResourceRequirements(
	cpuRequest, cpuLimit, memoryRequest, memoryLimit string,
) corev1.ResourceRequirements {
	return corev1.ResourceRequirements{
		Requests: corev1.ResourceList{
			corev1.ResourceCPU:                    resource.MustParse(cpuRequest),
			corev1.ResourceMemory:                 resource.MustParse(memoryRequest),
			corev1.ResourceName("nvidia.com/gpu"): resource.MustParse("0"),
		},
		Limits: corev1.ResourceList{
			corev1.ResourceCPU:                    resource.MustParse(cpuLimit),
			corev1.ResourceMemory:                 resource.MustParse(memoryLimit),
			corev1.ResourceName("nvidia.com/gpu"): resource.MustParse("0"),
		},
	}
}

func resourceTestScheme(t *testing.T) *runtime.Scheme {
	t.Helper()
	scheme := runtime.NewScheme()
	for name, addToScheme := range map[string]func(*runtime.Scheme) error{
		"apps/v1":             appsv1.AddToScheme,
		"core/v1":             corev1.AddToScheme,
		"rbac/v1":             rbacv1.AddToScheme,
		"production-stack/v1": productionstackv1alpha1.AddToScheme,
	} {
		if err := addToScheme(scheme); err != nil {
			t.Fatalf("add %s to scheme: %v", name, err)
		}
	}
	return scheme
}

type mutationCountingClient struct {
	client.Client
	mutations int
}

func (c *mutationCountingClient) Create(ctx context.Context, obj client.Object, opts ...client.CreateOption) error {
	c.mutations++
	return c.Client.Create(ctx, obj, opts...)
}

func (c *mutationCountingClient) Update(ctx context.Context, obj client.Object, opts ...client.UpdateOption) error {
	c.mutations++
	return c.Client.Update(ctx, obj, opts...)
}

func (c *mutationCountingClient) Patch(ctx context.Context, obj client.Object, patch client.Patch, opts ...client.PatchOption) error {
	c.mutations++
	return c.Client.Patch(ctx, obj, patch, opts...)
}

func (c *mutationCountingClient) Delete(ctx context.Context, obj client.Object, opts ...client.DeleteOption) error {
	c.mutations++
	return c.Client.Delete(ctx, obj, opts...)
}

func (c *mutationCountingClient) DeleteAllOf(ctx context.Context, obj client.Object, opts ...client.DeleteAllOfOption) error {
	c.mutations++
	return c.Client.DeleteAllOf(ctx, obj, opts...)
}
