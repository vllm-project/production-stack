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

package controller

import (
	"testing"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"

	productionstackv1alpha1 "production-stack/api/v1alpha1"
)

// podFieldsCacheServer builds a CacheServer with every pod-level field set.
func podFieldsCacheServer() *productionstackv1alpha1.CacheServer {
	cs := mpCacheServer()
	cs.Name, cs.Namespace = "cache", "default"
	cs.Spec.RuntimeClassName = "nvidia"
	cs.Spec.HostIPC = true
	cs.Spec.DeploymentStrategy = "Recreate"
	cs.Spec.Volumes = []corev1.Volume{{
		Name: "kvcache",
		VolumeSource: corev1.VolumeSource{
			PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{ClaimName: "kvcache"},
		},
	}}
	cs.Spec.VolumeMounts = []corev1.VolumeMount{{Name: "kvcache", MountPath: "/mnt/kvcache"}}
	return cs
}

// TestCacheServerPodFieldsReachPodSpec covers the fields that decide whether a
// lmcache_driven cache server can see the engines' GPUs and keep its L2 tier.
// Before these existed the only way to set them was a post-apply kubectl patch,
// which the operator silently reverted whenever it recreated the Deployment.
func TestCacheServerPodFieldsReachPodSpec(t *testing.T) {
	r := &CacheServerReconciler{Scheme: newTestScheme()}
	pod := r.deploymentForCacheServer(podFieldsCacheServer()).Spec.Template.Spec

	if pod.RuntimeClassName == nil || *pod.RuntimeClassName != "nvidia" {
		t.Errorf("runtimeClassName not applied: %v", pod.RuntimeClassName)
	}
	if !pod.HostIPC {
		t.Error("hostIPC not applied")
	}
	if len(pod.Volumes) != 1 || pod.Volumes[0].Name != "kvcache" {
		t.Errorf("volumes not applied: %#v", pod.Volumes)
	}
	if m := pod.Containers[0].VolumeMounts; len(m) != 1 || m[0].MountPath != "/mnt/kvcache" {
		t.Errorf("volumeMounts not applied: %#v", m)
	}
}

// TestCacheServerEmptyRuntimeClassIsNil checks the empty string maps to nil
// rather than to a pointer to "". A RuntimeClass named "" exists on no cluster,
// so the pod would be rejected at admission and never schedule.
func TestCacheServerEmptyRuntimeClassIsNil(t *testing.T) {
	r := &CacheServerReconciler{Scheme: newTestScheme()}
	cs := mpCacheServer()
	cs.Name = "cache"
	cs.Namespace = "default"
	cs.Spec.RuntimeClassName = ""

	if rc := r.deploymentForCacheServer(cs).Spec.Template.Spec.RuntimeClassName; rc != nil {
		t.Errorf("empty runtimeClassName became %q, want nil", *rc)
	}
}

// TestCacheServerStrategyRendered covers deploymentStrategy, which was accepted
// by the API and then dropped: the Deployment was always left on the
// RollingUpdate default. The cache server should use Recreate, because its L1
// arena is pinned host memory and two pods cannot hold it at once.
func TestCacheServerStrategyRendered(t *testing.T) {
	r := &CacheServerReconciler{Scheme: newTestScheme()}
	cs := mpCacheServer()
	cs.Name = "cache"
	cs.Namespace = "default"

	cs.Spec.DeploymentStrategy = "Recreate"
	if got := r.deploymentForCacheServer(cs).Spec.Strategy.Type; got != appsv1.RecreateDeploymentStrategyType {
		t.Errorf("Recreate not rendered, got %q", got)
	}

	cs.Spec.DeploymentStrategy = "RollingUpdate"
	if got := r.deploymentForCacheServer(cs).Spec.Strategy.Type; got != appsv1.RollingUpdateDeploymentStrategyType {
		t.Errorf("RollingUpdate not rendered, got %q", got)
	}
}

// TestCacheServerPodFieldsDrift checks a changed pod-level field actually rolls
// the pod. Without this the operator would accept an edited CR and leave the
// old pod running, for example under a RuntimeClass that hides the GPUs, where
// lmcache_driven falls back to StubCPUDevice and every engine fails to register.
func TestCacheServerPodFieldsDrift(t *testing.T) {
	r := &CacheServerReconciler{Scheme: newTestScheme()}
	stored := r.deploymentForCacheServer(podFieldsCacheServer())
	if r.deploymentNeedsUpdate(stored, podFieldsCacheServer()) {
		t.Fatal("unchanged spec reported as drift")
	}

	for name, mutate := range map[string]func(*productionstackv1alpha1.CacheServer){
		"runtimeClass change": func(cs *productionstackv1alpha1.CacheServer) { cs.Spec.RuntimeClassName = "" },
		"hostIPC change":      func(cs *productionstackv1alpha1.CacheServer) { cs.Spec.HostIPC = false },
		"strategy change":     func(cs *productionstackv1alpha1.CacheServer) { cs.Spec.DeploymentStrategy = "RollingUpdate" },
		"volume removed":      func(cs *productionstackv1alpha1.CacheServer) { cs.Spec.Volumes = nil },
		"mount moved": func(cs *productionstackv1alpha1.CacheServer) {
			cs.Spec.VolumeMounts = []corev1.VolumeMount{{Name: "kvcache", MountPath: "/data"}}
		},
		"env added": func(cs *productionstackv1alpha1.CacheServer) {
			cs.Spec.Env = []productionstackv1alpha1.EnvVar{{Name: "NVIDIA_VISIBLE_DEVICES", Value: "all"}}
		},
	} {
		cs := podFieldsCacheServer()
		mutate(cs)
		if !r.deploymentNeedsUpdate(stored, cs) {
			t.Errorf("%s not detected as drift", name)
		}
	}
}
