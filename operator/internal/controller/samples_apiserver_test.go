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
	"context"
	"os"
	"path/filepath"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/yaml"

	productionstackv1alpha1 "production-stack/api/v1alpha1"
)

// readSample parses one sample into obj, in the default namespace.
func readSample(name string, obj client.Object) {
	raw, err := os.ReadFile(filepath.Join(samplesDir, name))
	Expect(err).NotTo(HaveOccurred())
	Expect(yaml.UnmarshalStrict(raw, obj)).To(Succeed())
	if obj.GetNamespace() == "" {
		if _, clusterScoped := obj.(*corev1.PersistentVolume); !clusterScoped {
			obj.SetNamespace("default")
		}
	}
}

// These specs apply the samples to a real API server carrying the generated
// CRDs. They catch what the unit tests cannot: a field the schema
// prunes on apply, and a default the schema does not fill in.
var _ = Describe("Samples against the API server", func() {
	ctx := context.Background()

	It("accepts every sample and keeps its multiprocess fields", func() {
		pv := &corev1.PersistentVolume{}
		pvc := &corev1.PersistentVolumeClaim{}
		cs := &productionstackv1alpha1.CacheServer{}
		rt := &productionstackv1alpha1.VLLMRuntime{}
		router := &productionstackv1alpha1.VLLMRouter{}
		files := map[string]client.Object{
			sampleKVCachePVFile:   pv,
			sampleKVCachePVCFile:  pvc,
			sampleCacheServerFile: cs,
			sampleRuntimeFile:     rt,
			sampleRouterFile:      router,
		}
		for name, obj := range files {
			readSample(name, obj)
			Expect(k8sClient.Create(ctx, obj)).To(Succeed(), name)
			DeferCleanup(func() { _ = k8sClient.Delete(ctx, obj) })
		}

		got := &productionstackv1alpha1.CacheServer{}
		Expect(k8sClient.Get(ctx, client.ObjectKeyFromObject(cs), got)).To(Succeed())
		Expect(got.Spec.Multiprocess.TransferMode).To(Equal("lmcache_driven"), "transferMode default")
		Expect(got.Spec.Multiprocess.IsolatedIPC).To(BeTrue())
		Expect(got.Spec.Multiprocess.L2Adapters).To(Equal(cs.Spec.Multiprocess.L2Adapters))
		Expect(got.Spec.RuntimeClassName).To(Equal("nvidia"))
		Expect(got.Spec.Volumes).To(HaveLen(1))
		Expect(got.Spec.Volumes[0].PersistentVolumeClaim.ClaimName).To(Equal(pvc.Name))
		Expect(got.Spec.VolumeMounts).To(Equal(cs.Spec.VolumeMounts))

		gotRT := &productionstackv1alpha1.VLLMRuntime{}
		Expect(k8sClient.Get(ctx, client.ObjectKeyFromObject(rt), gotRT)).To(Succeed())
		mp := gotRT.Spec.LMCacheConfig.Multiprocess
		Expect(gotRT.Spec.LMCacheConfig.Mode).To(Equal(productionstackv1alpha1.LMCacheModeMultiprocess))
		Expect(mp.TransferMode).To(Equal("lmcache_driven"), "transferMode default")
		Expect(mp.Host).To(Equal(rt.Spec.LMCacheConfig.Multiprocess.Host))
		Expect(mp.Port).To(Equal(cs.Spec.Port))
		Expect(mp.IsolatedIPC).To(BeTrue())
		Expect(gotRT.Spec.VLLMConfig.MaxNumBatchedTokens).To(Equal(rt.Spec.VLLMConfig.MaxNumBatchedTokens))

		// The stored, defaulted objects must still render the MP stack.
		cmd := cacheServerCommand(got)
		Expect(argValue(cmd, "--supported-transfer-mode")).To(Equal("lmcache_driven"))
		Expect(lmcacheKVTransferConfig(gotRT)).To(ContainSubstring(`"lmcache.mp.mp_transfer_mode":"lmcache_driven"`))
	})

	It("defaults lmCacheConfig.mode to Multiprocess", func() {
		// A runtime that names no mode gets the multiprocess connector. The
		// in-process buffer sizes are still defaulted but not rendered.
		rt := &productionstackv1alpha1.VLLMRuntime{}
		readSample(sampleRuntimeFile, rt)
		rt.Name = "vllmruntime-no-mode"
		rt.Spec.LMCacheConfig = productionstackv1alpha1.LMCacheConfig{Enabled: true}
		Expect(k8sClient.Create(ctx, rt)).To(Succeed())
		DeferCleanup(func() { _ = k8sClient.Delete(ctx, rt) })

		got := &productionstackv1alpha1.VLLMRuntime{}
		Expect(k8sClient.Get(ctx, client.ObjectKeyFromObject(rt), got)).To(Succeed())
		Expect(got.Spec.LMCacheConfig.Mode).To(Equal(productionstackv1alpha1.LMCacheModeMultiprocess))
		Expect(lmcacheKVTransferConfig(got)).To(ContainSubstring(`"kv_connector":"LMCacheMPConnector"`))
	})

	It("keeps main's in-process defaults when mode is InProcess", func() {
		// A runtime written for main moves to InProcess by naming the mode,
		// and then comes back with the buffer sizes and connector it always had.
		rt := &productionstackv1alpha1.VLLMRuntime{}
		readSample(sampleRuntimeFile, rt)
		rt.Name = "vllmruntime-from-main"
		rt.Spec.LMCacheConfig = productionstackv1alpha1.LMCacheConfig{
			Enabled: true,
			Mode:    productionstackv1alpha1.LMCacheModeInProcess,
		}
		Expect(k8sClient.Create(ctx, rt)).To(Succeed())
		DeferCleanup(func() { _ = k8sClient.Delete(ctx, rt) })

		got := &productionstackv1alpha1.VLLMRuntime{}
		Expect(k8sClient.Get(ctx, client.ObjectKeyFromObject(rt), got)).To(Succeed())
		Expect(got.Spec.LMCacheConfig.Mode).To(Equal(productionstackv1alpha1.LMCacheModeInProcess))
		Expect(got.Spec.LMCacheConfig.CPUOffloadingBufferSize).To(Equal("4Gi"))
		Expect(got.Spec.LMCacheConfig.DiskOffloadingBufferSize).To(Equal("8Gi"))
		Expect(lmcacheKVTransferConfig(got)).To(Equal(`{"kv_connector":"LMCacheConnectorV1","kv_role":"kv_both"}`))
	})

	It("accepts the in-process sample and keeps disk offloading off", func() {
		// Applied as kubectl does, from the raw YAML: an explicit
		// diskOffloadingBufferSize: "" must survive, or the API fills in its
		// 8Gi default and the engine offloads to ephemeral disk.
		raw, err := os.ReadFile(filepath.Join(samplesDir, sampleInProcessFile))
		Expect(err).NotTo(HaveOccurred())
		obj := &unstructured.Unstructured{}
		Expect(yaml.Unmarshal(raw, &obj.Object)).To(Succeed())
		obj.SetNamespace("default")
		Expect(k8sClient.Create(ctx, obj)).To(Succeed())
		DeferCleanup(func() { _ = k8sClient.Delete(ctx, obj) })

		got := &productionstackv1alpha1.VLLMRuntime{}
		Expect(k8sClient.Get(ctx, client.ObjectKeyFromObject(obj), got)).To(Succeed())
		lm := got.Spec.LMCacheConfig
		Expect(lm.Mode).To(Equal(productionstackv1alpha1.LMCacheModeInProcess))
		Expect(lm.CPUOffloadingBufferSize).To(Equal("20"))
		Expect(lm.DiskOffloadingBufferSize).To(BeEmpty())

		env := map[string]string{}
		for _, e := range (&VLLMRuntimeReconciler{Scheme: newTestScheme()}).deploymentForVLLMRuntime(got).Spec.Template.Spec.Containers[0].Env {
			env[e.Name] = e.Value
		}
		Expect(env).To(HaveKeyWithValue("LMCACHE_MAX_LOCAL_CPU_SIZE", "20"))
		Expect(env).NotTo(HaveKey("LMCACHE_LOCAL_DISK"))
	})

	It("rejects transfer modes other than lmcache_driven", func() {
		cs := &productionstackv1alpha1.CacheServer{}
		readSample(sampleCacheServerFile, cs)
		cs.Name = "cacheserver-engine-driven"
		cs.Spec.Multiprocess.TransferMode = "engine_driven"
		err := k8sClient.Create(ctx, cs)
		Expect(apierrors.IsInvalid(err)).To(BeTrue(), "CacheServer engine_driven: %v", err)

		rt := &productionstackv1alpha1.VLLMRuntime{}
		readSample(sampleRuntimeFile, rt)
		rt.Name = "vllmruntime-auto"
		rt.Spec.LMCacheConfig.Multiprocess.TransferMode = "auto"
		err = k8sClient.Create(ctx, rt)
		Expect(apierrors.IsInvalid(err)).To(BeTrue(), "VLLMRuntime auto: %v", err)
	})

	It("rejects ports outside 1-65535", func() {
		for name, mutate := range map[string]func(*productionstackv1alpha1.CacheServer){
			"port 0":         func(cs *productionstackv1alpha1.CacheServer) { cs.Spec.Port = 0 },
			"port 70000":     func(cs *productionstackv1alpha1.CacheServer) { cs.Spec.Port = 70000 },
			"httpPort 70000": func(cs *productionstackv1alpha1.CacheServer) { cs.Spec.Multiprocess.HTTPPort = 70000 },
			"httpPort -1":    func(cs *productionstackv1alpha1.CacheServer) { cs.Spec.Multiprocess.HTTPPort = -1 },
		} {
			cs := &productionstackv1alpha1.CacheServer{}
			readSample(sampleCacheServerFile, cs)
			cs.Name = "cacheserver-bad-port"
			mutate(cs)
			err := k8sClient.Create(ctx, cs)
			Expect(apierrors.IsInvalid(err)).To(BeTrue(), "CacheServer %s: %v", name, err)
		}

		rt := &productionstackv1alpha1.VLLMRuntime{}
		readSample(sampleRuntimeFile, rt)
		rt.Name = "vllmruntime-bad-port"
		rt.Spec.LMCacheConfig.Multiprocess.Port = 70000
		err := k8sClient.Create(ctx, rt)
		Expect(apierrors.IsInvalid(err)).To(BeTrue(), "VLLMRuntime multiprocess.port 70000: %v", err)
	})
})
