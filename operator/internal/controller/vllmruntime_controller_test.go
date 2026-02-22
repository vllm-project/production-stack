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
	"context"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	productionstackv1alpha1 "production-stack/api/v1alpha1"
)

var _ = Describe("VLLMRuntime Controller", func() {
	// Test for PD Disaggregation mode (new feature)
	Context("When reconciling a PD disaggregation resource", func() {
		const resourceName = "test-pd-runtime"

		ctx := context.Background()

		typeNamespacedName := types.NamespacedName{
			Name:      resourceName,
			Namespace: "default",
		}

		BeforeEach(func() {
			By("creating the PD disaggregation VLLMRuntime resource")
			resource := &productionstackv1alpha1.VLLMRuntime{
				ObjectMeta: metav1.ObjectMeta{
					Name:      resourceName,
					Namespace: "default",
					Labels: map[string]string{
						"app.kubernetes.io/name":       "production-stack",
						"app.kubernetes.io/managed-by": "kustomize",
						"model":                        "Llama-3.2-3B-Instruct",
					},
				},
				Spec: productionstackv1alpha1.VLLMRuntimeSpec{
					EnablePDDisaggregation: true,
					Topology: &productionstackv1alpha1.TopologySpec{
						Prefill: productionstackv1alpha1.NodeConfig{
							Model: productionstackv1alpha1.ModelSpec{
								ModelURL:    "meta-llama/Llama-3.2-3B-Instruct",
								EnableLoRA:  true,
								MaxModelLen: 4096,
								DType:       "bfloat16",
								MaxNumSeqs:  32,
							},
							VLLMConfig: productionstackv1alpha1.VLLMConfig{
								EnableChunkedPrefill: false,
								EnablePrefixCaching:  false,
								TensorParallelSize:   1,
								GpuMemoryUtilization: "0.8",
								MaxLoras:             4,
								ExtraArgs:            []string{"--disable-log-requests"},
								V1:                   true,
								Port:                 8000,
								Env: []productionstackv1alpha1.EnvVar{
									{Name: "HF_HOME", Value: "/data"},
									{Name: "TRANSFORMERS_CACHE", Value: "/data/transformers_cache"},
									{Name: "HF_HUB_CACHE", Value: "/data/hf_hub_cache"},
								},
							},
							LMCacheConfig: productionstackv1alpha1.LMCacheConfig{
								Enabled:          true,
								KVRole:           "kv_producer",
								EnableNixl:       true,
								EnableXpyd:       true,
								NixlRole:         "sender",
								NixlProxyHost:    "vllm-router-service",
								NixlProxyPort:    "7500",
								NixlBufferSize:   "58720256",
								NixlBufferDevice: "cuda",
								RPCPort:          "producer1",
								RemoteSerde:      "naive",
							},
							StorageConfig: productionstackv1alpha1.StorageConfig{
								Enabled:    true,
								Size:       "10Gi",
								AccessMode: "ReadWriteMany",
								MountPath:  "/data",
							},
							DeploymentConfig: productionstackv1alpha1.DeploymentConfig{
								Replicas:       2,
								DeployStrategy: "Recreate",
								Resources: productionstackv1alpha1.ResourceRequirements{
									CPU:    "2",
									Memory: "16Gi",
									GPU:    "1",
								},
								Image: productionstackv1alpha1.ImageSpec{
									Registry:   "docker.io",
									Name:       "lmcache/vllm-openai:latest-nightly",
									PullPolicy: "IfNotPresent",
								},
								SidecarConfig: productionstackv1alpha1.SidecarConfig{
									Enabled: true,
									Name:    "sidecar",
									Image: productionstackv1alpha1.ImageSpec{
										Registry:   "docker.io",
										Name:       "lmcache/lmstack-sidecar:latest",
										PullPolicy: "Always",
									},
									Resources: productionstackv1alpha1.ResourceRequirements{
										CPU:    "0.5",
										Memory: "128Mi",
									},
									MountPath: "/data",
								},
							},
						},
						Decode: productionstackv1alpha1.NodeConfig{
							Model: productionstackv1alpha1.ModelSpec{
								ModelURL:    "meta-llama/Llama-3.2-3B-Instruct",
								EnableLoRA:  true,
								MaxModelLen: 4096,
								DType:       "bfloat16",
								MaxNumSeqs:  32,
							},
							VLLMConfig: productionstackv1alpha1.VLLMConfig{
								EnableChunkedPrefill: false,
								EnablePrefixCaching:  false,
								TensorParallelSize:   1,
								GpuMemoryUtilization: "0.8",
								MaxLoras:             4,
								ExtraArgs:            []string{"--disable-log-requests"},
								V1:                   true,
								Port:                 8000,
								Env: []productionstackv1alpha1.EnvVar{
									{Name: "HF_HOME", Value: "/data"},
									{Name: "TRANSFORMERS_CACHE", Value: "/data/transformers_cache"},
									{Name: "HF_HUB_CACHE", Value: "/data/hf_hub_cache"},
								},
							},
							LMCacheConfig: productionstackv1alpha1.LMCacheConfig{
								Enabled:           true,
								KVRole:            "kv_consumer",
								EnableNixl:        true,
								EnableXpyd:        true,
								NixlRole:          "receiver",
								NixlPeerHost:      "0.0.0.0",
								NixlPeerInitPort:  "7300",
								NixlPeerAllocPort: "7400",
								NixlBufferSize:    "58720256",
								NixlBufferDevice:  "cuda",
								RPCPort:           "consumer1",
								SkipLastNTokens:   1,
								RemoteSerde:       "naive",
							},
							StorageConfig: productionstackv1alpha1.StorageConfig{
								Enabled:    true,
								Size:       "10Gi",
								AccessMode: "ReadWriteMany",
								MountPath:  "/data",
							},
							DeploymentConfig: productionstackv1alpha1.DeploymentConfig{
								Replicas:       2,
								DeployStrategy: "Recreate",
								Resources: productionstackv1alpha1.ResourceRequirements{
									CPU:    "2",
									Memory: "16Gi",
									GPU:    "1",
								},
								Image: productionstackv1alpha1.ImageSpec{
									Registry:   "docker.io",
									Name:       "lmcache/vllm-openai:latest-nightly",
									PullPolicy: "IfNotPresent",
								},
								SidecarConfig: productionstackv1alpha1.SidecarConfig{
									Enabled: true,
									Name:    "sidecar",
									Image: productionstackv1alpha1.ImageSpec{
										Registry:   "docker.io",
										Name:       "lmcache/lmstack-sidecar:latest",
										PullPolicy: "Always",
									},
									Resources: productionstackv1alpha1.ResourceRequirements{
										CPU:    "0.5",
										Memory: "128Mi",
									},
									MountPath: "/data",
								},
							},
						},
					},
				},
			}

			err := k8sClient.Get(ctx, typeNamespacedName, &productionstackv1alpha1.VLLMRuntime{})
			if err != nil && errors.IsNotFound(err) {
				Expect(k8sClient.Create(ctx, resource)).To(Succeed())
			}
		})

		AfterEach(func() {
			By("Cleanup the PD VLLMRuntime resource")
			resource := &productionstackv1alpha1.VLLMRuntime{}
			err := k8sClient.Get(ctx, typeNamespacedName, resource)
			if err == nil {
				Expect(k8sClient.Delete(ctx, resource)).To(Succeed())
			}
		})

		It("should successfully reconcile PD disaggregation and create prefill/decode deployments", func() {
			By("Reconciling the created resource")
			controllerReconciler := &VLLMRuntimeReconciler{
				Client: k8sClient,
				Scheme: k8sClient.Scheme(),
			}

			// Reconcile multiple times to handle the requeue behavior
			for i := 0; i < 3; i++ {
				_, err := controllerReconciler.Reconcile(ctx, reconcile.Request{
					NamespacedName: typeNamespacedName,
				})
				Expect(err).NotTo(HaveOccurred())
			}

			By("Verifying prefill deployment is created")
			prefillDeployment := &appsv1.Deployment{}
			prefillName := types.NamespacedName{
				Name:      resourceName + "-prefill",
				Namespace: "default",
			}
			Eventually(func() error {
				return k8sClient.Get(ctx, prefillName, prefillDeployment)
			}).Should(Succeed())

			// Verify prefill deployment has correct labels
			Expect(prefillDeployment.Labels["app"]).To(Equal(resourceName))
			Expect(prefillDeployment.Labels["node-type"]).To(Equal("prefill"))
			Expect(prefillDeployment.Labels["model"]).To(Equal("Llama-3.2-3B-Instruct-prefill"))
			Expect(prefillDeployment.Spec.Replicas).To(Equal(int32Ptr(2)))

			By("Verifying decode deployment is created")
			decodeDeployment := &appsv1.Deployment{}
			decodeName := types.NamespacedName{
				Name:      resourceName + "-decode",
				Namespace: "default",
			}
			Eventually(func() error {
				return k8sClient.Get(ctx, decodeName, decodeDeployment)
			}).Should(Succeed())

			// Verify decode deployment has correct labels
			Expect(decodeDeployment.Labels["model"]).To(Equal("Llama-3.2-3B-Instruct-decode"))
			Expect(decodeDeployment.Labels["app"]).To(Equal(resourceName))
			Expect(decodeDeployment.Labels["node-type"]).To(Equal("decode"))
			Expect(decodeDeployment.Spec.Replicas).To(Equal(int32Ptr(2)))

			By("Verifying services are created")
			prefillService := &corev1.Service{}
			prefillServiceName := types.NamespacedName{
				Name:      resourceName + "-prefill",
				Namespace: "default",
			}
			Eventually(func() error {
				return k8sClient.Get(ctx, prefillServiceName, prefillService)
			}).Should(Succeed())

			decodeService := &corev1.Service{}
			decodeServiceName := types.NamespacedName{
				Name:      resourceName + "-decode",
				Namespace: "default",
			}
			Eventually(func() error {
				return k8sClient.Get(ctx, decodeServiceName, decodeService)
			}).Should(Succeed())
		})

		It("should handle LMCache configuration correctly for PD mode", func() {
			By("Reconciling the created resource first")
			controllerReconciler := &VLLMRuntimeReconciler{
				Client: k8sClient,
				Scheme: k8sClient.Scheme(),
			}

			// Reconcile multiple times to handle the requeue behavior
			for i := 0; i < 3; i++ {
				_, err := controllerReconciler.Reconcile(ctx, reconcile.Request{
					NamespacedName: typeNamespacedName,
				})
				Expect(err).NotTo(HaveOccurred())
			}

			By("Verifying LMCache environment variables in prefill deployment")
			prefillDeployment := &appsv1.Deployment{}
			prefillName := types.NamespacedName{
				Name:      resourceName + "-prefill",
				Namespace: "default",
			}

			Eventually(func() error {
				return k8sClient.Get(ctx, prefillName, prefillDeployment)
			}).Should(Succeed())

			// Check that prefill has producer role
			container := prefillDeployment.Spec.Template.Spec.Containers[0]
			envVars := container.Env

			var kvRoleFound bool
			for _, env := range envVars {
				if env.Name == "LMCACHE_KV_ROLE" && env.Value == "kv_producer" {
					kvRoleFound = true
					break
				}
			}
			Expect(kvRoleFound).To(BeTrue(), "Prefill deployment should have LMCACHE_KV_ROLE=kv_producer")

			By("Verifying LMCache environment variables in decode deployment")
			decodeDeployment := &appsv1.Deployment{}
			decodeName := types.NamespacedName{
				Name:      resourceName + "-decode",
				Namespace: "default",
			}

			Eventually(func() error {
				return k8sClient.Get(ctx, decodeName, decodeDeployment)
			}).Should(Succeed())

			// Check that decode has consumer role
			container = decodeDeployment.Spec.Template.Spec.Containers[0]
			envVars = container.Env

			kvRoleFound = false
			for _, env := range envVars {
				if env.Name == "LMCACHE_KV_ROLE" && env.Value == "kv_consumer" {
					kvRoleFound = true
					break
				}
			}
			Expect(kvRoleFound).To(BeTrue(), "Decode deployment should have LMCACHE_KV_ROLE=kv_consumer")
		})
	})

	// Test for Legacy mode (backward compatibility)
	Context("When reconciling a legacy (non-PD) resource", func() {
		const legacyResourceName = "test-legacy-runtime"

		ctx := context.Background()

		typeNamespacedName := types.NamespacedName{
			Name:      legacyResourceName,
			Namespace: "default",
		}

		BeforeEach(func() {
			By("creating a legacy VLLMRuntime resource")
			resource := &productionstackv1alpha1.VLLMRuntime{
				ObjectMeta: metav1.ObjectMeta{
					Name:      legacyResourceName,
					Namespace: "default",
				},
				Spec: productionstackv1alpha1.VLLMRuntimeSpec{
					EnablePDDisaggregation: false,
					Model: productionstackv1alpha1.ModelSpec{
						ModelURL:    "meta-llama/Llama-3.2-3B-Instruct",
						MaxModelLen: 4096,
						DType:       "bfloat16",
					},
					VLLMConfig: productionstackv1alpha1.VLLMConfig{
						Port: 8000,
						V1:   true,
					},
					DeploymentConfig: productionstackv1alpha1.DeploymentConfig{
						Replicas: 1,
						Resources: productionstackv1alpha1.ResourceRequirements{
							CPU:    "2",
							Memory: "8Gi",
							GPU:    "1",
						},
						Image: productionstackv1alpha1.ImageSpec{
							Registry:   "docker.io",
							Name:       "vllm/vllm-openai:latest",
							PullPolicy: "IfNotPresent",
						},
					},
				},
			}

			err := k8sClient.Get(ctx, typeNamespacedName, &productionstackv1alpha1.VLLMRuntime{})
			if err != nil && errors.IsNotFound(err) {
				Expect(k8sClient.Create(ctx, resource)).To(Succeed())
			}
		})

		AfterEach(func() {
			By("Cleanup the legacy VLLMRuntime resource")
			resource := &productionstackv1alpha1.VLLMRuntime{}
			err := k8sClient.Get(ctx, typeNamespacedName, resource)
			if err == nil {
				Expect(k8sClient.Delete(ctx, resource)).To(Succeed())
			}
		})

		It("should successfully reconcile the legacy resource", func() {
			By("Reconciling the legacy resource")
			controllerReconciler := &VLLMRuntimeReconciler{
				Client: k8sClient,
				Scheme: k8sClient.Scheme(),
			}

			// Reconcile multiple times to handle the requeue behavior
			for i := 0; i < 3; i++ {
				_, err := controllerReconciler.Reconcile(ctx, reconcile.Request{
					NamespacedName: typeNamespacedName,
				})
				Expect(err).NotTo(HaveOccurred())
			}
		})

		It("should create a single unified deployment for legacy mode", func() {
			By("Verifying single deployment is created")
			deployment := &appsv1.Deployment{}
			deploymentName := types.NamespacedName{
				Name:      legacyResourceName,
				Namespace: "default",
			}
			Eventually(func() error {
				return k8sClient.Get(ctx, deploymentName, deployment)
			}).Should(Succeed())

			Expect(deployment.Spec.Replicas).To(Equal(int32Ptr(1)))

			By("Verifying no separate prefill/decode deployments exist")
			prefillDeployment := &appsv1.Deployment{}
			prefillName := types.NamespacedName{
				Name:      legacyResourceName + "-prefill",
				Namespace: "default",
			}
			err := k8sClient.Get(ctx, prefillName, prefillDeployment)
			Expect(errors.IsNotFound(err)).To(BeTrue(), "Prefill deployment should not exist in legacy mode")

			decodeDeployment := &appsv1.Deployment{}
			decodeName := types.NamespacedName{
				Name:      legacyResourceName + "-decode",
				Namespace: "default",
			}
			err = k8sClient.Get(ctx, decodeName, decodeDeployment)
			Expect(errors.IsNotFound(err)).To(BeTrue(), "Decode deployment should not exist in legacy mode")
		})

		It("should handle legacy configuration correctly", func() {
			By("Verifying legacy deployment uses correct image and configuration")
			deployment := &appsv1.Deployment{}
			deploymentName := types.NamespacedName{
				Name:      legacyResourceName,
				Namespace: "default",
			}
			Eventually(func() error {
				return k8sClient.Get(ctx, deploymentName, deployment)
			}).Should(Succeed())

			// Verify legacy deployment configuration
			container := deployment.Spec.Template.Spec.Containers[0]
			Expect(container.Image).To(ContainSubstring("vllm/vllm-openai:latest"))

			// Verify no PD-specific environment variables
			envVars := container.Env
			for _, env := range envVars {
				Expect(env.Name).ToNot(Equal("LMCACHE_KV_ROLE"), "Legacy mode should not have KV role")
				Expect(env.Name).ToNot(Equal("LMCACHE_NIXL_ROLE"), "Legacy mode should not have Nixl role")
			}
		})
	})

	// Test for configuration validation
	Context("When validating configuration", func() {
		const validationResourceName = "test-validation"

		ctx := context.Background()

		typeNamespacedName := types.NamespacedName{
			Name:      validationResourceName,
			Namespace: "default",
		}

		AfterEach(func() {
			By("Cleanup validation test resource")
			resource := &productionstackv1alpha1.VLLMRuntime{}
			err := k8sClient.Get(ctx, typeNamespacedName, resource)
			if err == nil {
				Expect(k8sClient.Delete(ctx, resource)).To(Succeed())
			}
		})

		It("should handle invalid PD configuration gracefully", func() {
			By("creating VLLMRuntime with PD enabled but no topology")
			resource := &productionstackv1alpha1.VLLMRuntime{
				ObjectMeta: metav1.ObjectMeta{
					Name:      validationResourceName,
					Namespace: "default",
				},
				Spec: productionstackv1alpha1.VLLMRuntimeSpec{
					EnablePDDisaggregation: true,
					// Missing Topology - should cause validation error or default behavior
				},
			}

			err := k8sClient.Create(ctx, resource)
			// This might succeed with defaults or fail with validation - both are acceptable
			if err == nil {
				By("Reconciling the invalid resource")
				controllerReconciler := &VLLMRuntimeReconciler{
					Client: k8sClient,
					Scheme: k8sClient.Scheme(),
				}

				_, reconcileErr := controllerReconciler.Reconcile(ctx, reconcile.Request{
					NamespacedName: typeNamespacedName,
				})
				// Controller should handle this gracefully (either with defaults or proper error)
				// We don't expect a panic or unhandled error
				if reconcileErr != nil {
					By("Controller properly handled invalid configuration with error: " + reconcileErr.Error())
				}
			}
		})
	})
})

// Helper function to create int32 pointer
func int32Ptr(i int32) *int32 {
	return &i
}
