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

package controller

import (
	"reflect"
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	v1alpha1 "production-stack/api/v1alpha1"
)

func testPodSecurityContext() *corev1.PodSecurityContext {
	runAsNonRoot := true
	return &corev1.PodSecurityContext{
		RunAsNonRoot: &runAsNonRoot,
		SeccompProfile: &corev1.SeccompProfile{
			Type: corev1.SeccompProfileTypeRuntimeDefault,
		},
	}
}

func testContainerSecurityContext() *corev1.SecurityContext {
	allowPrivilegeEscalation := false
	return &corev1.SecurityContext{
		AllowPrivilegeEscalation: &allowPrivilegeEscalation,
		Capabilities: &corev1.Capabilities{
			Drop: []corev1.Capability{"ALL"},
		},
	}
}

func TestVLLMRouterSecurityContextPropagation(t *testing.T) {
	r := &VLLMRouterReconciler{Scheme: newTestScheme()}

	router := buildTestRouter("roundrobin", "", 0)
	router.Spec.PodSecurityContext = testPodSecurityContext()
	router.Spec.SecurityContext = testContainerSecurityContext()

	dep := r.deploymentForVLLMRouter(router)
	if dep == nil {
		t.Fatal("deploymentForVLLMRouter returned nil")
	}
	if !reflect.DeepEqual(dep.Spec.Template.Spec.SecurityContext, router.Spec.PodSecurityContext) {
		t.Errorf("pod security context = %#v, want %#v", dep.Spec.Template.Spec.SecurityContext, router.Spec.PodSecurityContext)
	}
	if len(dep.Spec.Template.Spec.Containers) != 1 {
		t.Fatalf("deployment has %d containers, want 1", len(dep.Spec.Template.Spec.Containers))
	}
	if !reflect.DeepEqual(dep.Spec.Template.Spec.Containers[0].SecurityContext, router.Spec.SecurityContext) {
		t.Errorf("container security context = %#v, want %#v", dep.Spec.Template.Spec.Containers[0].SecurityContext, router.Spec.SecurityContext)
	}

	existing := r.deploymentForVLLMRouter(buildTestRouter("roundrobin", "", 0))
	if !r.deploymentNeedsUpdate(existing, router) {
		t.Error("expected update when security contexts are added")
	}
}

func TestVLLMRouterSecurityContextUnset(t *testing.T) {
	r := &VLLMRouterReconciler{Scheme: newTestScheme()}

	dep := r.deploymentForVLLMRouter(buildTestRouter("roundrobin", "", 0))
	if dep == nil {
		t.Fatal("deploymentForVLLMRouter returned nil")
	}
	if dep.Spec.Template.Spec.SecurityContext != nil {
		t.Errorf("pod security context = %#v, want nil", dep.Spec.Template.Spec.SecurityContext)
	}
	if len(dep.Spec.Template.Spec.Containers) != 1 {
		t.Fatalf("deployment has %d containers, want 1", len(dep.Spec.Template.Spec.Containers))
	}
	if dep.Spec.Template.Spec.Containers[0].SecurityContext != nil {
		t.Errorf("container security context = %#v, want nil", dep.Spec.Template.Spec.Containers[0].SecurityContext)
	}
}

func buildTestCacheServer() *v1alpha1.CacheServer {
	return &v1alpha1.CacheServer{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-cache-server",
			Namespace: "default",
		},
		Spec: v1alpha1.CacheServerSpec{
			Image: v1alpha1.ImageSpec{
				Registry: "docker.io",
				Name:     "lmcache/cache-server:latest",
			},
			Port:               8000,
			Replicas:           1,
			DeploymentStrategy: "RollingUpdate",
		},
	}
}

func TestCacheServerSecurityContextPropagation(t *testing.T) {
	r := &CacheServerReconciler{Scheme: newTestScheme()}

	cacheServer := buildTestCacheServer()
	cacheServer.Spec.PodSecurityContext = testPodSecurityContext()
	cacheServer.Spec.SecurityContext = testContainerSecurityContext()

	dep := r.deploymentForCacheServer(cacheServer)
	if dep == nil {
		t.Fatal("deploymentForCacheServer returned nil")
	}
	if !reflect.DeepEqual(dep.Spec.Template.Spec.SecurityContext, cacheServer.Spec.PodSecurityContext) {
		t.Errorf("pod security context = %#v, want %#v", dep.Spec.Template.Spec.SecurityContext, cacheServer.Spec.PodSecurityContext)
	}
	if len(dep.Spec.Template.Spec.Containers) != 1 {
		t.Fatalf("deployment has %d containers, want 1", len(dep.Spec.Template.Spec.Containers))
	}
	if !reflect.DeepEqual(dep.Spec.Template.Spec.Containers[0].SecurityContext, cacheServer.Spec.SecurityContext) {
		t.Errorf("container security context = %#v, want %#v", dep.Spec.Template.Spec.Containers[0].SecurityContext, cacheServer.Spec.SecurityContext)
	}

	existing := r.deploymentForCacheServer(buildTestCacheServer())
	if !r.deploymentNeedsUpdate(existing, cacheServer) {
		t.Error("expected update when security contexts are added")
	}
}

func TestCacheServerSecurityContextUnset(t *testing.T) {
	r := &CacheServerReconciler{Scheme: newTestScheme()}

	dep := r.deploymentForCacheServer(buildTestCacheServer())
	if dep == nil {
		t.Fatal("deploymentForCacheServer returned nil")
	}
	if dep.Spec.Template.Spec.SecurityContext != nil {
		t.Errorf("pod security context = %#v, want nil", dep.Spec.Template.Spec.SecurityContext)
	}
	if len(dep.Spec.Template.Spec.Containers) != 1 {
		t.Fatalf("deployment has %d containers, want 1", len(dep.Spec.Template.Spec.Containers))
	}
	if dep.Spec.Template.Spec.Containers[0].SecurityContext != nil {
		t.Errorf("container security context = %#v, want nil", dep.Spec.Template.Spec.Containers[0].SecurityContext)
	}
}
