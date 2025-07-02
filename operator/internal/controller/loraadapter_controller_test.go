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
	"time"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	productionstackv1alpha1 "production-stack/api/v1alpha1"

	corev1 "k8s.io/api/core/v1"
)

var _ = Describe("LoraAdapterReconciler", func() {
	const (
		timeout  = time.Second * 10
		interval = time.Millisecond * 250
	)

	Context("When reconciling a LoraAdapter", func() {
		var (
			ctx            context.Context
			reconciler     *LoraAdapterReconciler
			loraAdapter    *productionstackv1alpha1.LoraAdapter
			namespace      string
			loraAdapterKey types.NamespacedName
		)

		BeforeEach(func() {
			ctx = context.Background()
			namespace = "default"
			loraAdapterKey = types.NamespacedName{
				Name:      "test-adapter",
				Namespace: namespace,
			}

			// Create a test LoraAdapter
			loraAdapter = &productionstackv1alpha1.LoraAdapter{
				ObjectMeta: metav1.ObjectMeta{
					Name:      loraAdapterKey.Name,
					Namespace: loraAdapterKey.Namespace,
				},
				Spec: productionstackv1alpha1.LoraAdapterSpec{
					BaseModel: "llama-3-1-8b",
					AdapterSource: productionstackv1alpha1.AdapterSource{
						Type:        "local",
						AdapterName: "test-adapter",
						AdapterPath: "/path/to/adapter",
					},
					LoraAdapterDeploymentConfig: productionstackv1alpha1.LoraAdapterDeploymentConfig{
						Replicas: nil, // Use all available pods
					},
				},
			}

			// Create the LoraAdapter in the cluster
			Expect(k8sClient.Create(ctx, loraAdapter)).Should(Succeed())
		})

		AfterEach(func() {
			// Clean up the LoraAdapter
			Expect(k8sClient.Delete(ctx, loraAdapter)).Should(Succeed())
		})

		It("Should successfully reconcile a LoraAdapter", func() {
			By("Creating a test pod")
			testPod := &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-pod",
					Namespace: namespace,
					Labels: map[string]string{
						"model": "test-model",
					},
				},
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{
						{
							Name:  "test-container",
							Image: "test-image",
							Ports: []corev1.ContainerPort{
								{
									Name:          "container-port",
									ContainerPort: 8000,
								},
							},
						},
					},
				},
				Status: corev1.PodStatus{
					Phase: corev1.PodRunning,
					PodIP: "10.0.0.1",
				},
			}
			Expect(k8sClient.Create(ctx, testPod)).Should(Succeed())

			By("Reconciling the LoraAdapter")
			_, err := reconciler.Reconcile(ctx, reconcile.Request{
				NamespacedName: loraAdapterKey,
			})
			Expect(err).ToNot(HaveOccurred())

			By("Checking the LoraAdapter status")
			Eventually(func() string {
				var updatedAdapter productionstackv1alpha1.LoraAdapter
				err := k8sClient.Get(ctx, loraAdapterKey, &updatedAdapter)
				if err != nil {
					return ""
				}
				return updatedAdapter.Status.Phase
			}, timeout, interval).Should(Equal("Loaded"))

			By("Verifying the adapter was loaded on the pod")
			Eventually(func() int {
				var updatedAdapter productionstackv1alpha1.LoraAdapter
				err := k8sClient.Get(ctx, loraAdapterKey, &updatedAdapter)
				if err != nil {
					return 0
				}
				return len(updatedAdapter.Status.LoadedAdapters)
			}, timeout, interval).Should(Equal(1))
		})

		It("Should handle adapter deletion", func() {
			By("Adding a finalizer to the LoraAdapter")
			loraAdapter.Finalizers = append(loraAdapter.Finalizers, "loraadapter.finalizers.production-stack.vllm.ai")
			Expect(k8sClient.Update(ctx, loraAdapter)).Should(Succeed())

			By("Deleting the LoraAdapter")
			Expect(k8sClient.Delete(ctx, loraAdapter)).Should(Succeed())

			By("Verifying the finalizer is removed")
			Eventually(func() []string {
				var updatedAdapter productionstackv1alpha1.LoraAdapter
				err := k8sClient.Get(ctx, loraAdapterKey, &updatedAdapter)
				if err != nil {
					return []string{"error"}
				}
				return updatedAdapter.Finalizers
			}, timeout, interval).Should(BeEmpty())
		})

		It("Should handle missing pods gracefully", func() {
			By("Reconciling the LoraAdapter with no pods")
			_, err := reconciler.Reconcile(ctx, reconcile.Request{
				NamespacedName: loraAdapterKey,
			})
			Expect(err).ToNot(HaveOccurred())

			By("Checking the LoraAdapter status shows waiting condition")
			Eventually(func() bool {
				var updatedAdapter productionstackv1alpha1.LoraAdapter
				err := k8sClient.Get(ctx, loraAdapterKey, &updatedAdapter)
				if err != nil {
					return false
				}
				// Check if there's a waiting condition
				for _, condition := range updatedAdapter.Status.Conditions {
					if condition.Type == "WaitingForPods" && condition.Status == "True" {
						return true
					}
				}
				return false
			}, timeout, interval).Should(BeTrue())

			By("Verifying no adapters are loaded when no pods are ready")
			var updatedAdapter productionstackv1alpha1.LoraAdapter
			err = k8sClient.Get(ctx, loraAdapterKey, &updatedAdapter)
			Expect(err).ToNot(HaveOccurred())
			Expect(len(updatedAdapter.Status.LoadedAdapters)).To(Equal(0))
		})

		It("Should transition from waiting to loaded when pods become ready", func() {
			By("Reconciling the LoraAdapter with no pods initially")
			_, err := reconciler.Reconcile(ctx, reconcile.Request{
				NamespacedName: loraAdapterKey,
			})
			Expect(err).ToNot(HaveOccurred())

			By("Verifying waiting condition is set")
			Eventually(func() bool {
				var updatedAdapter productionstackv1alpha1.LoraAdapter
				err := k8sClient.Get(ctx, loraAdapterKey, &updatedAdapter)
				if err != nil {
					return false
				}
				for _, condition := range updatedAdapter.Status.Conditions {
					if condition.Type == "WaitingForPods" && condition.Status == "True" {
						return true
					}
				}
				return false
			}, timeout, interval).Should(BeTrue())

			By("Creating a ready pod")
			testPod := &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{
					Name:      "test-pod-ready",
					Namespace: namespace,
					Labels: map[string]string{
						"model": "llama-3-1-8b", // Match the adapter's base model
					},
				},
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{
						{
							Name:  "test-container",
							Image: "test-image",
							Ports: []corev1.ContainerPort{
								{
									Name:          "container-port",
									ContainerPort: 8000,
								},
							},
						},
					},
				},
				Status: corev1.PodStatus{
					Phase: corev1.PodRunning,
					PodIP: "10.0.0.1",
					Conditions: []corev1.PodCondition{
						{
							Type:   corev1.PodReady,
							Status: corev1.ConditionTrue,
						},
					},
				},
			}
			Expect(k8sClient.Create(ctx, testPod)).Should(Succeed())

			By("Reconciling again after pod becomes ready")
			_, err = reconciler.Reconcile(ctx, reconcile.Request{
				NamespacedName: loraAdapterKey,
			})
			Expect(err).ToNot(HaveOccurred())

			By("Verifying waiting condition is cleared")
			Eventually(func() bool {
				var updatedAdapter productionstackv1alpha1.LoraAdapter
				err := k8sClient.Get(ctx, loraAdapterKey, &updatedAdapter)
				if err != nil {
					return false
				}
				// Check that waiting condition is not present
				for _, condition := range updatedAdapter.Status.Conditions {
					if condition.Type == "WaitingForPods" {
						return false
					}
				}
				return true
			}, timeout, interval).Should(BeTrue())

			// Clean up the test pod
			Expect(k8sClient.Delete(ctx, testPod)).Should(Succeed())
		})
	})
})

// Helper function to create string pointer
func stringPtr(s string) *string {
	return &s
}

// Mock getPodEndpoint function
var getPodEndpoint func(ctx context.Context, podName, namespace, path string) (string, error)
