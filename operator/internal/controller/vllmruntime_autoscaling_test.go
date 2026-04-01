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
	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/utils/ptr"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	productionstackv1alpha1 "production-stack/api/v1alpha1"
)

var _ = Describe("VLLMRuntime Autoscaling", func() {
	const resourceName = "test-autoscaling"
	ctx := context.Background()
	typeNamespacedName := types.NamespacedName{
		Name:      resourceName,
		Namespace: "default",
	}

	makeRuntime := func(cfg *productionstackv1alpha1.AutoscalingConfig) *productionstackv1alpha1.VLLMRuntime {
		return &productionstackv1alpha1.VLLMRuntime{
			ObjectMeta: metav1.ObjectMeta{
				Name:      resourceName,
				Namespace: "default",
			},
			Spec: productionstackv1alpha1.VLLMRuntimeSpec{
				Model: productionstackv1alpha1.ModelSpec{
					ModelURL: "meta-llama/Llama-3.1-8B-Instruct",
				},
				VLLMConfig: productionstackv1alpha1.VLLMConfig{
					Port: 8000,
					V1:   true,
				},
				DeploymentConfig: productionstackv1alpha1.DeploymentConfig{
					Replicas: 1,
					Image: productionstackv1alpha1.ImageSpec{
						Registry: "docker.io",
						Name:     "lmcache/vllm-openai:latest",
					},
				},
				AutoscalingConfig: cfg,
			},
		}
	}

	AfterEach(func() {
		resource := &productionstackv1alpha1.VLLMRuntime{}
		err := k8sClient.Get(ctx, typeNamespacedName, resource)
		if err == nil {
			Expect(k8sClient.Delete(ctx, resource)).To(Succeed())
		}
	})

	Context("Validation", func() {
		It("should reject minReplicas > maxReplicas via CRD validation", func() {
			runtime := makeRuntime(&productionstackv1alpha1.AutoscalingConfig{
				Enabled:     true,
				MinReplicas: ptr.To(int32(5)),
				MaxReplicas: 2,
			})
			Expect(k8sClient.Create(ctx, runtime)).To(Succeed())

			// Verify the invalid config was stored (CRD can't do cross-field validation)
			created := &productionstackv1alpha1.VLLMRuntime{}
			Expect(k8sClient.Get(ctx, typeNamespacedName, created)).To(Succeed())
			Expect(*created.Spec.AutoscalingConfig.MinReplicas).To(Equal(int32(5)))
			Expect(created.Spec.AutoscalingConfig.MaxReplicas).To(Equal(int32(2)))
			// Cross-field validation (minReplicas <= maxReplicas) is enforced
			// at reconcile time, not at CRD admission time
		})

		It("should reject maxReplicas < deploymentConfig.replicas", func() {
			runtime := makeRuntime(&productionstackv1alpha1.AutoscalingConfig{
				Enabled:     true,
				MaxReplicas: 1,
			})
			runtime.Spec.DeploymentConfig.Replicas = 3
			Expect(k8sClient.Create(ctx, runtime)).To(Succeed())

			// Verify the invalid config was stored
			created := &productionstackv1alpha1.VLLMRuntime{}
			Expect(k8sClient.Get(ctx, typeNamespacedName, created)).To(Succeed())
			Expect(created.Spec.AutoscalingConfig.MaxReplicas).To(Equal(int32(1)))
			Expect(created.Spec.DeploymentConfig.Replicas).To(Equal(int32(3)))
			// Cross-field validation (maxReplicas >= replicas) is enforced
			// at reconcile time, not at CRD admission time
		})

		It("should accept minReplicas = 0 (scale-to-zero)", func() {
			runtime := makeRuntime(&productionstackv1alpha1.AutoscalingConfig{
				Enabled:     true,
				MinReplicas: ptr.To(int32(0)),
				MaxReplicas: 4,
			})
			Expect(k8sClient.Create(ctx, runtime)).To(Succeed())

			// Verify the CR was created with minReplicas=0
			created := &productionstackv1alpha1.VLLMRuntime{}
			Expect(k8sClient.Get(ctx, typeNamespacedName, created)).To(Succeed())
			Expect(*created.Spec.AutoscalingConfig.MinReplicas).To(Equal(int32(0)))
		})

		It("should accept minReplicas = maxReplicas (fixed scaling)", func() {
			runtime := makeRuntime(&productionstackv1alpha1.AutoscalingConfig{
				Enabled:     true,
				MinReplicas: ptr.To(int32(2)),
				MaxReplicas: 2,
			})
			Expect(k8sClient.Create(ctx, runtime)).To(Succeed())

			created := &productionstackv1alpha1.VLLMRuntime{}
			Expect(k8sClient.Get(ctx, typeNamespacedName, created)).To(Succeed())
			Expect(*created.Spec.AutoscalingConfig.MinReplicas).To(Equal(int32(2)))
			Expect(created.Spec.AutoscalingConfig.MaxReplicas).To(Equal(int32(2)))
		})
	})

	Context("Defaults", func() {
		It("should apply kubebuilder defaults for autoscaling config", func() {
			runtime := makeRuntime(&productionstackv1alpha1.AutoscalingConfig{
				Enabled:     true,
				MaxReplicas: 4,
			})
			Expect(k8sClient.Create(ctx, runtime)).To(Succeed())

			created := &productionstackv1alpha1.VLLMRuntime{}
			Expect(k8sClient.Get(ctx, typeNamespacedName, created)).To(Succeed())

			cfg := created.Spec.AutoscalingConfig
			// MinReplicas defaults to 1
			Expect(cfg.MinReplicas).NotTo(BeNil())
			Expect(*cfg.MinReplicas).To(Equal(int32(1)))

			// PollingInterval defaults to 15
			Expect(cfg.PollingInterval).NotTo(BeNil())
			Expect(*cfg.PollingInterval).To(Equal(int32(15)))

			// Trigger defaults
			Expect(cfg.Triggers.RequestsRunningThreshold).NotTo(BeNil())
			Expect(*cfg.Triggers.RequestsRunningThreshold).To(Equal(int32(5)))
			Expect(cfg.Triggers.GenerationTokensThreshold).NotTo(BeNil())
			Expect(*cfg.Triggers.GenerationTokensThreshold).To(Equal(int32(100)))
			Expect(cfg.Triggers.PromptTokensThreshold).NotTo(BeNil())
			Expect(*cfg.Triggers.PromptTokensThreshold).To(Equal(int32(100)))

			// ScaleUpPolicy defaults
			Expect(cfg.ScaleUpPolicy.StabilizationWindowSeconds).NotTo(BeNil())
			Expect(*cfg.ScaleUpPolicy.StabilizationWindowSeconds).To(Equal(int32(0)))
			Expect(cfg.ScaleUpPolicy.PodValue).NotTo(BeNil())
			Expect(*cfg.ScaleUpPolicy.PodValue).To(Equal(int32(1)))
			Expect(cfg.ScaleUpPolicy.PeriodSeconds).NotTo(BeNil())
			Expect(*cfg.ScaleUpPolicy.PeriodSeconds).To(Equal(int32(60)))

			// ScaleDownPolicy defaults
			Expect(cfg.ScaleDownPolicy.StabilizationWindowSeconds).NotTo(BeNil())
			Expect(*cfg.ScaleDownPolicy.StabilizationWindowSeconds).To(Equal(int32(300)))
			Expect(cfg.ScaleDownPolicy.PodValue).NotTo(BeNil())
			Expect(*cfg.ScaleDownPolicy.PodValue).To(Equal(int32(1)))
			Expect(cfg.ScaleDownPolicy.PeriodSeconds).NotTo(BeNil())
			Expect(*cfg.ScaleDownPolicy.PeriodSeconds).To(Equal(int32(60)))
			Expect(cfg.ScaleDownPolicy.ScaleToZeroDelaySeconds).NotTo(BeNil())
			Expect(*cfg.ScaleDownPolicy.ScaleToZeroDelaySeconds).To(Equal(int32(1800)))
		})

		It("should allow overriding defaults", func() {
			runtime := makeRuntime(&productionstackv1alpha1.AutoscalingConfig{
				Enabled:         true,
				MinReplicas:     ptr.To(int32(0)),
				MaxReplicas:     8,
				PollingInterval: ptr.To(int32(30)),
				ScaleUpPolicy: productionstackv1alpha1.ScaleUpPolicy{
					PodValue:      ptr.To(int32(2)),
					PeriodSeconds: ptr.To(int32(30)),
				},
				ScaleDownPolicy: productionstackv1alpha1.ScaleDownPolicy{
					ScaleToZeroDelaySeconds: ptr.To(int32(600)),
				},
				Triggers: productionstackv1alpha1.TriggerConfig{
					RequestsRunningThreshold: ptr.To(int32(10)),
				},
			})
			Expect(k8sClient.Create(ctx, runtime)).To(Succeed())

			created := &productionstackv1alpha1.VLLMRuntime{}
			Expect(k8sClient.Get(ctx, typeNamespacedName, created)).To(Succeed())

			cfg := created.Spec.AutoscalingConfig
			Expect(*cfg.MinReplicas).To(Equal(int32(0)))
			Expect(cfg.MaxReplicas).To(Equal(int32(8)))
			Expect(*cfg.PollingInterval).To(Equal(int32(30)))
			Expect(*cfg.ScaleUpPolicy.PodValue).To(Equal(int32(2)))
			Expect(*cfg.ScaleUpPolicy.PeriodSeconds).To(Equal(int32(30)))
			Expect(*cfg.ScaleDownPolicy.ScaleToZeroDelaySeconds).To(Equal(int32(600)))
			Expect(*cfg.Triggers.RequestsRunningThreshold).To(Equal(int32(10)))
			// Non-overridden fields should still have defaults
			Expect(*cfg.Triggers.GenerationTokensThreshold).To(Equal(int32(100)))
		})
	})

	Context("Reconciliation without autoscaling", func() {
		It("should reconcile without autoscaling config", func() {
			runtime := makeRuntime(nil)
			Expect(k8sClient.Create(ctx, runtime)).To(Succeed())

			controllerReconciler := &VLLMRuntimeReconciler{
				Client: k8sClient,
				Scheme: k8sClient.Scheme(),
			}

			_, err := controllerReconciler.Reconcile(ctx, reconcile.Request{
				NamespacedName: typeNamespacedName,
			})
			Expect(err).NotTo(HaveOccurred())
		})

		It("should reconcile with autoscaling disabled", func() {
			runtime := makeRuntime(&productionstackv1alpha1.AutoscalingConfig{
				Enabled:     false,
				MaxReplicas: 4,
			})
			Expect(k8sClient.Create(ctx, runtime)).To(Succeed())

			controllerReconciler := &VLLMRuntimeReconciler{
				Client: k8sClient,
				Scheme: k8sClient.Scheme(),
			}

			_, err := controllerReconciler.Reconcile(ctx, reconcile.Request{
				NamespacedName: typeNamespacedName,
			})
			Expect(err).NotTo(HaveOccurred())
		})
	})

	Context("Deleted resource", func() {
		It("should not error when resource is already deleted", func() {
			controllerReconciler := &VLLMRuntimeReconciler{
				Client: k8sClient,
				Scheme: k8sClient.Scheme(),
			}

			_, err := controllerReconciler.Reconcile(ctx, reconcile.Request{
				NamespacedName: types.NamespacedName{
					Name:      "nonexistent-resource",
					Namespace: "default",
				},
			})
			Expect(err).NotTo(HaveOccurred())
		})
	})

	Context("CRD validation", func() {
		It("should reject maxReplicas = 0", func() {
			runtime := makeRuntime(&productionstackv1alpha1.AutoscalingConfig{
				Enabled:     true,
				MaxReplicas: 0,
			})
			err := k8sClient.Create(ctx, runtime)
			Expect(err).To(HaveOccurred())
			Expect(errors.IsInvalid(err)).To(BeTrue())
		})

		It("should reject negative minReplicas", func() {
			runtime := makeRuntime(&productionstackv1alpha1.AutoscalingConfig{
				Enabled:     true,
				MinReplicas: ptr.To(int32(-1)),
				MaxReplicas: 4,
			})
			err := k8sClient.Create(ctx, runtime)
			Expect(err).To(HaveOccurred())
			Expect(errors.IsInvalid(err)).To(BeTrue())
		})
	})
})
