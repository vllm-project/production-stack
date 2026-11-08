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
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	"sigs.k8s.io/yaml"

	productionstackv1alpha1 "production-stack/api/v1alpha1"
)

// The multiprocess samples (cache server, its KV-cache disk, runtime and
// router) only work together. Nothing else checks that they agree, and each
// disagreement below fails at runtime without a useful error: a transfer-mode
// mismatch hangs the engine until mq_timeout, and an L2 base_path that misses
// its mount silently writes the cold tier to ephemeral container disk.
const samplesDir = "../../config/samples"

const (
	sampleCacheServerFile = "production-stack_v1alpha1_cacheserver.yaml"
	sampleRuntimeFile     = "production-stack_v1alpha1_vllmruntime.yaml"
	sampleInProcessFile   = "production-stack_v1alpha1_vllmruntime_inprocess.yaml"
	sampleRouterFile      = "production-stack_v1alpha1_vllmrouter.yaml"
	sampleKVCachePVFile   = "cacheserver-kvcache-pv.yaml"
	sampleKVCachePVCFile  = "cacheserver-kvcache-pvc.yaml"
)

func loadSample[T any](t *testing.T, name string) *T {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(samplesDir, name))
	if err != nil {
		t.Fatalf("reading %s: %v", name, err)
	}
	out := new(T)
	// UnmarshalStrict rejects unknown fields, so a sample that names a field
	// the CRD does not have fails here rather than being silently pruned by
	// the API server on apply.
	if err := yaml.UnmarshalStrict(raw, out); err != nil {
		t.Fatalf("parsing %s: %v", name, err)
	}
	return out
}

func sampleCacheServer(t *testing.T) *productionstackv1alpha1.CacheServer {
	return loadSample[productionstackv1alpha1.CacheServer](t, sampleCacheServerFile)
}

func sampleRuntime(t *testing.T) *productionstackv1alpha1.VLLMRuntime {
	return loadSample[productionstackv1alpha1.VLLMRuntime](t, sampleRuntimeFile)
}

func sampleRouter(t *testing.T) *productionstackv1alpha1.VLLMRouter {
	return loadSample[productionstackv1alpha1.VLLMRouter](t, sampleRouterFile)
}

func sampleKVCachePV(t *testing.T) *corev1.PersistentVolume {
	return loadSample[corev1.PersistentVolume](t, sampleKVCachePVFile)
}

func sampleKVCachePVC(t *testing.T) *corev1.PersistentVolumeClaim {
	return loadSample[corev1.PersistentVolumeClaim](t, sampleKVCachePVCFile)
}

// TestSamplesKustomizationListsMultiprocessStack checks `kubectl apply -k`
// deploys the whole multiprocess stack. A file left out of kustomization.yaml
// still passes every other test here, then is simply never applied.
func TestSamplesKustomizationListsMultiprocessStack(t *testing.T) {
	k := loadSample[struct {
		APIVersion string   `json:"apiVersion"`
		Kind       string   `json:"kind"`
		Resources  []string `json:"resources"`
	}](t, "kustomization.yaml")

	for _, name := range []string{
		sampleKVCachePVFile, sampleKVCachePVCFile,
		sampleCacheServerFile, sampleRuntimeFile, sampleRouterFile,
	} {
		if !slices.Contains(k.Resources, name) {
			t.Errorf("%s is not listed in kustomization.yaml", name)
		}
	}
	// The in-process runtime is an alternative to the multiprocess one, not
	// part of the stack; listing it would deploy both.
	if slices.Contains(k.Resources, sampleInProcessFile) {
		t.Errorf("%s is listed in kustomization.yaml next to the multiprocess runtime", sampleInProcessFile)
	}
}

// TestSamplesInProcessRuntime checks the in-process sample names its mode,
// which is not the default, and renders the in-process connector.
func TestSamplesInProcessRuntime(t *testing.T) {
	rt := loadSample[productionstackv1alpha1.VLLMRuntime](t, sampleInProcessFile)
	if rt.Spec.LMCacheConfig.Mode != productionstackv1alpha1.LMCacheModeInProcess {
		t.Errorf("in-process sample lmCacheConfig.mode = %q, want InProcess", rt.Spec.LMCacheConfig.Mode)
	}
	if got := lmcacheKVTransferConfig(rt); !strings.Contains(got, `"kv_connector":"LMCacheConnectorV1"`) {
		t.Errorf("in-process sample kv-transfer-config = %s, want LMCacheConnectorV1", got)
	}
	if rt.Name == sampleRuntime(t).Name {
		t.Errorf("in-process and multiprocess samples share the name %q, so applying one replaces the other", rt.Name)
	}
}

// TestSamplesLMCacheMultiprocess checks the runtime sample turns on LMCache in
// Multiprocess mode. Left off, the engine runs with no KV connector; left on
// the InProcess default, it keeps its own cache. Either way the cache server
// sits idle.
func TestSamplesLMCacheMultiprocess(t *testing.T) {
	rt := sampleRuntime(t)
	if !rt.Spec.LMCacheConfig.Enabled {
		t.Error("runtime lmCacheConfig.enabled is false")
	}
	if rt.Spec.LMCacheConfig.Mode != productionstackv1alpha1.LMCacheModeMultiprocess {
		t.Errorf("runtime lmCacheConfig.mode = %q, want Multiprocess", rt.Spec.LMCacheConfig.Mode)
	}
}

// TestSamplesTransferModeAgrees is the mismatch with the worst symptom: the
// engine hangs at "Wrapping N KV cache tensors for IPC" for the whole
// mq_timeout, and the only clue is a server-side line about an unhandled
// REGISTER_KV_CACHE request. The samples leave the mode to its default, so
// both sides must resolve to lmcache_driven.
func TestSamplesTransferModeAgrees(t *testing.T) {
	cs := sampleCacheServer(t)
	rt := sampleRuntime(t)

	server := mpTransferMode(cs.Spec.Multiprocess.TransferMode)
	engine := mpTransferMode(rt.Spec.LMCacheConfig.Multiprocess.TransferMode)
	if server != "lmcache_driven" || engine != "lmcache_driven" {
		t.Errorf("transferMode: cache server %q, runtime %q, want lmcache_driven on both", server, engine)
	}
	if cs.Spec.Multiprocess.IsolatedIPC != rt.Spec.LMCacheConfig.Multiprocess.IsolatedIPC {
		t.Errorf("isolatedIpc: cache server %v, runtime %v -- separate pods have separate IPC namespaces, so both must be true",
			cs.Spec.Multiprocess.IsolatedIPC, rt.Spec.LMCacheConfig.Multiprocess.IsolatedIPC)
	}
}

// TestSamplesRuntimeTargetsCacheServer checks the runtime's host names the
// Service the CacheServer sample creates, on a port that Service publishes.
func TestSamplesRuntimeTargetsCacheServer(t *testing.T) {
	cs := sampleCacheServer(t)
	rt := sampleRuntime(t)

	host := rt.Spec.LMCacheConfig.Multiprocess.Host
	if !strings.HasPrefix(host, "tcp://"+cs.Name+".") {
		t.Errorf("runtime host %q does not name the CacheServer Service %q", host, cs.Name)
	}
	port := rt.Spec.LMCacheConfig.Multiprocess.Port
	if port != cs.Spec.Port {
		t.Errorf("runtime port %d, cache server port %d", port, cs.Spec.Port)
	}
	if !slices.ContainsFunc(cacheServerServicePorts(cs), func(p corev1.ServicePort) bool { return p.Port == port }) {
		t.Errorf("the cache server Service does not publish port %d", port)
	}
}

// TestSamplesL2AdapterIsMountedAndBounded checks the failures that make an L2
// tier useless rather than broken, so none shows up as an error: a base_path
// that is not on the KV-cache claim, a capacity larger than the claim, and a
// capacity with no eviction block behind it.
func TestSamplesL2AdapterIsMountedAndBounded(t *testing.T) {
	cs := sampleCacheServer(t)
	pvc := sampleKVCachePVC(t)

	if len(cs.Spec.Multiprocess.L2Adapters) == 0 {
		t.Fatal("sample declares no L2 adapter")
	}
	var spec struct {
		Type          string  `json:"type"`
		BasePath      string  `json:"base_path"`
		MaxCapacityGB float64 `json:"max_capacity_gb"`
		Eviction      *struct {
			EvictionPolicy string `json:"eviction_policy"`
		} `json:"eviction"`
	}
	if err := json.Unmarshal([]byte(cs.Spec.Multiprocess.L2Adapters[0]), &spec); err != nil {
		t.Fatalf("l2Adapters[0] is not valid JSON: %v", err)
	}

	var mount *corev1.VolumeMount
	for i, m := range cs.Spec.VolumeMounts {
		if spec.BasePath == m.MountPath || strings.HasPrefix(spec.BasePath, strings.TrimSuffix(m.MountPath, "/")+"/") {
			mount = &cs.Spec.VolumeMounts[i]
		}
	}
	if mount == nil {
		t.Fatalf("L2 base_path %q is not under any volumeMount; the cold tier would write to ephemeral container disk",
			spec.BasePath)
	}
	idx := slices.IndexFunc(cs.Spec.Volumes, func(v corev1.Volume) bool { return v.Name == mount.Name })
	if idx < 0 {
		t.Fatalf("volumeMount %q has no matching volume", mount.Name)
	}
	if v := cs.Spec.Volumes[idx]; v.PersistentVolumeClaim == nil || v.PersistentVolumeClaim.ClaimName != pvc.Name {
		t.Errorf("L2 volume %q does not use the KV-cache claim %q", v.Name, pvc.Name)
	}

	// The adapter does not know the volume size, so a capacity above it fills
	// the disk before eviction ever starts.
	request := pvc.Spec.Resources.Requests[corev1.ResourceStorage]
	capacity := resource.MustParse(fmt.Sprintf("%gGi", spec.MaxCapacityGB))
	if spec.MaxCapacityGB <= 0 || capacity.Cmp(request) >= 0 {
		t.Errorf("max_capacity_gb %v must be set and below the claim's %s", spec.MaxCapacityGB, request.String())
	}

	// A declared capacity without an eviction block only logs a warning and
	// keeps writing, so the volume fills up.
	if spec.MaxCapacityGB > 0 && spec.Eviction == nil {
		t.Error("max_capacity_gb is set with no eviction block: it is accounting only and will NOT bound disk usage")
	}
	if spec.Eviction != nil {
		switch spec.Eviction.EvictionPolicy {
		case "LRU", "IsolatedLRU", "noop":
		default:
			t.Errorf("eviction_policy %q is not one of LRU, IsolatedLRU, noop", spec.Eviction.EvictionPolicy)
		}
	}
}

// TestSamplesKVCacheClaimBindsToVolume checks the claim binds to the sample
// volume rather than staying Pending or having the default StorageClass
// provision a different disk.
func TestSamplesKVCacheClaimBindsToVolume(t *testing.T) {
	pv := sampleKVCachePV(t)
	pvc := sampleKVCachePVC(t)

	if pvc.Spec.VolumeName != pv.Name {
		t.Errorf("claim volumeName %q, want the sample volume %q", pvc.Spec.VolumeName, pv.Name)
	}
	if pvc.Spec.StorageClassName == nil || *pvc.Spec.StorageClassName != pv.Spec.StorageClassName {
		t.Errorf("claim storageClassName %v, volume %q: they must match, or the default class provisions a new disk",
			pvc.Spec.StorageClassName, pv.Spec.StorageClassName)
	}
	for _, m := range pvc.Spec.AccessModes {
		if !slices.Contains(pv.Spec.AccessModes, m) {
			t.Errorf("claim access mode %s is not offered by the volume %v", m, pv.Spec.AccessModes)
		}
	}
	request := pvc.Spec.Resources.Requests[corev1.ResourceStorage]
	if capacity := pv.Spec.Capacity[corev1.ResourceStorage]; capacity.Cmp(request) < 0 {
		t.Errorf("volume capacity %s is below the claim's %s", capacity.String(), request.String())
	}
	if pv.Spec.HostPath == nil {
		t.Error("the sample volume should be a hostPath on the node's local drive")
	}
}

// TestSamplesRouterSelectsRuntime checks the router's label selector matches
// the labels the operator copies from the VLLMRuntime onto its pods. A
// selector that matches nothing leaves the router healthy and serving 503s.
func TestSamplesRouterSelectsRuntime(t *testing.T) {
	router := sampleRouter(t)
	rt := sampleRuntime(t)

	sel := router.Spec.K8sLabelSelector
	if sel == "" {
		t.Fatal("router has no k8sLabelSelector")
	}
	// Pod labels are {"app": <name>} merged with the runtime's own labels.
	podLabels := map[string]string{"app": rt.Name}
	for k, v := range rt.Labels {
		podLabels[k] = v
	}
	for _, clause := range strings.Split(sel, ",") {
		k, v, ok := strings.Cut(strings.TrimSpace(clause), "=")
		if !ok {
			t.Errorf("selector clause %q is not key=value", clause)
			continue
		}
		if podLabels[k] != v {
			t.Errorf("router selects %s=%s but runtime pods carry %s=%q", k, v, k, podLabels[k])
		}
	}
}

// TestSamplesRouterAvoidsControllerRouting checks the router does not use a
// routing logic that needs engines registered with the LMCache controller,
// which MP engines do not do yet.
func TestSamplesRouterAvoidsControllerRouting(t *testing.T) {
	switch logic := sampleRouter(t).Spec.RoutingLogic; logic {
	case "kvaware", "loadaware":
		t.Errorf("routingLogic %q needs the LMCache controller, which MP engines do not register with", logic)
	}
}

// TestSamplesChunkSizeMatchesBatchTokens checks that a maxNumBatchedTokens the
// runtime sets is sized so a prefill covers whole cache chunks rather than
// straddling them. Left unset, vLLM picks its own default.
func TestSamplesChunkSizeMatchesBatchTokens(t *testing.T) {
	cs := sampleCacheServer(t)
	rt := sampleRuntime(t)

	chunk := cs.Spec.Multiprocess.ChunkSize
	if chunk == 0 {
		t.Fatal("cache server declares no chunkSize")
	}
	batched := rt.Spec.VLLMConfig.MaxNumBatchedTokens
	if batched != 0 && (batched < chunk || batched%chunk != 0) {
		t.Errorf("maxNumBatchedTokens %d is not a multiple of chunkSize %d", batched, chunk)
	}
}

// TestSamplesImagesMatch checks the cache server and engines run the same
// LMCache build. The two exchange KV over a private protocol with no version
// negotiation, so a mismatch corrupts or drops cache entries.
func TestSamplesImagesMatch(t *testing.T) {
	cs := sampleCacheServer(t)
	rt := sampleRuntime(t)

	server := cs.Spec.Image.Registry + "/" + cs.Spec.Image.Name
	engine := rt.Spec.DeploymentConfig.Image.Registry + "/" + rt.Spec.DeploymentConfig.Image.Name
	if server != engine {
		t.Errorf("image mismatch: cache server %q, engine %q", server, engine)
	}
}

// TestSamplesRenderValidPodSpecs runs the samples through the same builders the
// controllers use, so a sample that parses but renders the wrong pod is caught
// here rather than on the cluster.
func TestSamplesRenderValidPodSpecs(t *testing.T) {
	csr := &CacheServerReconciler{Scheme: newTestScheme()}
	cs := sampleCacheServer(t)
	cs.Namespace = "default"
	dep := csr.deploymentForCacheServer(cs)

	if len(dep.Spec.Template.Spec.Containers) != 1 {
		t.Fatalf("cache server rendered %d containers", len(dep.Spec.Template.Spec.Containers))
	}
	c := dep.Spec.Template.Spec.Containers[0]
	if _, ok := c.Resources.Limits[corev1.ResourceName("nvidia.com/gpu")]; ok {
		t.Error("cache server requests a GPU; it must see the engines' GPUs without owning one")
	}
	if len(c.VolumeMounts) == 0 {
		t.Error("cache server rendered no volume mounts, so the L2 tier has no backing store")
	}
	if !slices.Contains(c.Command, "--supported-transfer-mode") {
		t.Errorf("cache server command is not the MP server: %v", c.Command)
	}
	if dep.Spec.Strategy.Type != appsv1.RecreateDeploymentStrategyType {
		t.Errorf("cache server strategy = %q, want Recreate for a pinned L1 arena", dep.Spec.Strategy.Type)
	}

	vr := &VLLMRuntimeReconciler{Scheme: newTestScheme()}
	rt := sampleRuntime(t)
	rt.Namespace = "default"
	pod := vr.deploymentForVLLMRuntime(rt).Spec.Template.Spec
	args := pod.Containers[0].Args
	if cfg := argValue(args, "--kv-transfer-config"); !strings.Contains(cfg, "LMCacheMPConnector") {
		t.Errorf("runtime kv-transfer-config = %q, want LMCacheMPConnector", cfg)
	}
	// The cache lives in the cache server, so none of the in-process LMCache
	// settings may reach the engine.
	for _, e := range pod.Containers[0].Env {
		if _, inProcess := lmcacheEnvValues([]corev1.EnvVar{e})[e.Name]; inProcess {
			t.Errorf("runtime renders in-process LMCache env %s=%s", e.Name, e.Value)
		}
	}

	rr := &VLLMRouterReconciler{Scheme: newTestScheme()}
	router := sampleRouter(t)
	router.Namespace = "default"
	if n := len(rr.deploymentForVLLMRouter(router).Spec.Template.Spec.Containers); n != 1 {
		t.Fatalf("router rendered %d containers", n)
	}
}
