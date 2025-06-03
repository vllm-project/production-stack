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
	"fmt"
	"reflect"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/intstr"
	"k8s.io/client-go/util/retry"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/log"

	servingv1alpha1 "production-stack/api/v1alpha1"
)

// VLLMRouterReconciler reconciles a VLLMRouter object
type VLLMRouterReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

// +kubebuilder:rbac:groups=production-stack.vllm.ai,resources=vllmrouters,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=production-stack.vllm.ai,resources=vllmrouters/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=production-stack.vllm.ai,resources=vllmrouters/finalizers,verbs=update
// +kubebuilder:rbac:groups=production-stack.vllm.ai,resources=vllmruntimes,verbs=get;list;watch
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=configmaps,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=secrets,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=services,verbs=get;list;watch;create;update;patch;delete

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
func (r *VLLMRouterReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := log.FromContext(ctx)

	// Fetch the VLLMRouter instance
	router := &servingv1alpha1.VLLMRouter{}
	err := r.Get(ctx, req.NamespacedName, router)
	if err != nil {
		if errors.IsNotFound(err) {
			// Request object not found, could have been deleted after reconcile request.
			// Return and don't requeue
			log.Info("VLLMRouter resource not found. Ignoring since object must be deleted")
			return ctrl.Result{}, nil
		}
		// Error reading the object - requeue the request.
		log.Error(err, "Failed to get VLLMRouter")
		return ctrl.Result{}, err
	}

	// Check if the service already exists, if not create a new one
	foundService := &corev1.Service{}
	err = r.Get(ctx, types.NamespacedName{Name: router.Name, Namespace: router.Namespace}, foundService)
	if err != nil && errors.IsNotFound(err) {
		// Define a new service
		svc := r.serviceForVLLMRouter(router)
		log.Info("Creating a new Service", "Service.Namespace", svc.Namespace, "Service.Name", svc.Name)
		err = r.Create(ctx, svc)
		if err != nil {
			log.Error(err, "Failed to create new Service", "Service.Namespace", svc.Namespace, "Service.Name", svc.Name)
			return ctrl.Result{}, err
		}
		// Service created successfully - return and requeue
		return ctrl.Result{Requeue: true}, nil
	} else if err != nil {
		log.Error(err, "Failed to get Service")
		return ctrl.Result{}, err
	}

	// Check if the deployment already exists, if not create a new one
	found := &appsv1.Deployment{}
	err = r.Get(ctx, types.NamespacedName{Name: router.Name, Namespace: router.Namespace}, found)
	if err != nil && errors.IsNotFound(err) {
		// Define a new deployment
		dep := r.deploymentForVLLMRouter(router)
		log.Info("Creating a new Deployment", "Deployment.Namespace", dep.Namespace, "Deployment.Name", dep.Name)
		err = r.Create(ctx, dep)
		if err != nil {
			log.Error(err, "Failed to create new Deployment", "Deployment.Namespace", dep.Namespace, "Deployment.Name", dep.Name)
			return ctrl.Result{}, err
		}
		// Deployment created successfully - return and requeue
		return ctrl.Result{Requeue: true}, nil
	} else if err != nil {
		log.Error(err, "Failed to get Deployment")
		return ctrl.Result{}, err
	}

	// Update the deployment if needed
	if r.deploymentNeedsUpdate(found, router) {
		log.Info("Updating Deployment", "Deployment.Namespace", found.Namespace, "Deployment.Name", found.Name)
		// Create new deployment spec
		newDep := r.deploymentForVLLMRouter(router)

		err = r.Update(ctx, newDep)
		if err != nil {
			log.Error(err, "Failed to update Deployment", "Deployment.Namespace", found.Namespace, "Deployment.Name", found.Name)
			return ctrl.Result{}, err
		}
		// Deployment updated successfully - return and requeue
		return ctrl.Result{Requeue: true}, nil
	}

	// Update the status
	if err := r.updateStatus(ctx, router, found); err != nil {
		log.Error(err, "Failed to update VLLMRouter status")
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, nil
}

// deploymentForVLLMRouter returns a VLLMRouter Deployment object
func (r *VLLMRouterReconciler) deploymentForVLLMRouter(router *servingv1alpha1.VLLMRouter) *appsv1.Deployment {
	labels := map[string]string{
		"app": router.Name,
	}

	// Add user-defined environment variables
	env := []corev1.EnvVar{}
	if router.Spec.Env != nil {
		for _, e := range router.Spec.Env {
			env = append(env, corev1.EnvVar{
				Name:  e.Name,
				Value: e.Value,
			})
		}
	}

	// Add VLLM API Key if specified
	if router.Spec.VLLMApiKeySecret.Name != "" && router.Spec.VLLMApiKeyName != "" {
		env = append(env, corev1.EnvVar{
			Name: "VLLM_API_KEY",
			ValueFrom: &corev1.EnvVarSource{
				SecretKeyRef: &corev1.SecretKeySelector{
					LocalObjectReference: router.Spec.VLLMApiKeySecret,
					Key:                  router.Spec.VLLMApiKeyName,
				},
			},
		})
	}

	// Build resource requirements
	resources := corev1.ResourceRequirements{
		Requests: corev1.ResourceList{},
		Limits:   corev1.ResourceList{},
	}

	if router.Spec.Resources.CPU != "" {
		resources.Requests[corev1.ResourceCPU] = resource.MustParse(router.Spec.Resources.CPU)
		resources.Limits[corev1.ResourceCPU] = resource.MustParse(router.Spec.Resources.CPU)
	}

	if router.Spec.Resources.Memory != "" {
		resources.Requests[corev1.ResourceMemory] = resource.MustParse(router.Spec.Resources.Memory)
		resources.Limits[corev1.ResourceMemory] = resource.MustParse(router.Spec.Resources.Memory)
	}

	// Get the image from Image spec or use default
	image := router.Spec.Image.Registry + "/" + router.Spec.Image.Name

	// Get the image pull policy
	imagePullPolicy := corev1.PullIfNotPresent
	if router.Spec.Image.PullPolicy != "" {
		imagePullPolicy = corev1.PullPolicy(router.Spec.Image.PullPolicy)
	}

	// Build image pull secrets
	var imagePullSecrets []corev1.LocalObjectReference
	if router.Spec.Image.PullSecretName != "" {
		imagePullSecrets = append(imagePullSecrets, corev1.LocalObjectReference{
			Name: router.Spec.Image.PullSecretName,
		})
	}

	// Build container args
	args := []string{
		"--host", "0.0.0.0",
		"--port", fmt.Sprintf("%d", router.Spec.Port),
		"--service-discovery", router.Spec.ServiceDiscovery,
	}

	// Add service discovery specific args
	if router.Spec.ServiceDiscovery == "k8s" {
		args = append(args,
			"--k8s-namespace", router.Namespace,
			"--k8s-label-selector", router.Spec.K8sLabelSelector,
		)
	} else if router.Spec.ServiceDiscovery == "static" {
		if router.Spec.StaticBackends == "" || router.Spec.StaticModels == "" {
			// This should be handled by validation webhook
			panic("static service discovery requires both staticBackends and staticModels")
		}
		args = append(args,
			"--static-backends", router.Spec.StaticBackends,
			"--static-models", router.Spec.StaticModels,
		)
	}

	// Add optional args
	if router.Spec.RoutingLogic != "" {
		args = append(args, "--routing-logic", router.Spec.RoutingLogic)
	}
	if router.Spec.SessionKey != "" {
		args = append(args, "--session-key", router.Spec.SessionKey)
	}
	if router.Spec.EngineScrapeInterval != 0 {
		args = append(args, "--engine-stats-interval", fmt.Sprintf("%d", router.Spec.EngineScrapeInterval))
	}
	if router.Spec.RequestStatsWindow != 0 {
		args = append(args, "--request-stats-window", fmt.Sprintf("%d", router.Spec.RequestStatsWindow))
	}
	if router.Spec.ExtraArgs != nil {
		args = append(args, router.Spec.ExtraArgs...)
	}

	dep := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      router.Name,
			Namespace: router.Namespace,
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &router.Spec.Replicas,
			Selector: &metav1.LabelSelector{
				MatchLabels: labels,
			},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
				},
				Spec: corev1.PodSpec{
					ServiceAccountName: router.Spec.ServiceAccountName,
					ImagePullSecrets:   imagePullSecrets,
					Containers: []corev1.Container{
						{
							Name:            "router",
							Image:           image,
							ImagePullPolicy: imagePullPolicy,
							Args:            args,
							Env:             env,
							Ports: []corev1.ContainerPort{
								{
									Name:          "http",
									ContainerPort: router.Spec.Port,
								},
							},
							Resources: resources,
							LivenessProbe: &corev1.Probe{
								InitialDelaySeconds: 30,
								PeriodSeconds:       5,
								FailureThreshold:    3,
								ProbeHandler: corev1.ProbeHandler{
									HTTPGet: &corev1.HTTPGetAction{
										Path: "/health",
										Port: intstr.FromInt32(router.Spec.Port),
									},
								},
							},
						},
					},
				},
			},
		},
	}

	// Add node affinity if specified
	if router.Spec.NodeSelectorTerms != nil {
		dep.Spec.Template.Spec.Affinity = &corev1.Affinity{
			NodeAffinity: &corev1.NodeAffinity{
				RequiredDuringSchedulingIgnoredDuringExecution: &corev1.NodeSelector{
					NodeSelectorTerms: router.Spec.NodeSelectorTerms,
				},
			},
		}
	}

	// Set the owner reference
	ctrl.SetControllerReference(router, dep, r.Scheme)
	return dep
}

// deploymentNeedsUpdate checks if the deployment needs to be updated
func (r *VLLMRouterReconciler) deploymentNeedsUpdate(dep *appsv1.Deployment, router *servingv1alpha1.VLLMRouter) bool {
	// Generate the expected deployment
	expectedDep := r.deploymentForVLLMRouter(router)

	// Compare image
	if expectedDep.Spec.Template.Spec.Containers[0].Image != dep.Spec.Template.Spec.Containers[0].Image {
		return true
	}

	// Compare resources
	expectedResources := expectedDep.Spec.Template.Spec.Containers[0].Resources
	actualResources := dep.Spec.Template.Spec.Containers[0].Resources
	if !reflect.DeepEqual(expectedResources, actualResources) {
		return true
	}

	return false
}

// updateStatus updates the status of the VLLMRouter
func (r *VLLMRouterReconciler) updateStatus(ctx context.Context, router *servingv1alpha1.VLLMRouter, dep *appsv1.Deployment) error {
	return retry.RetryOnConflict(retry.DefaultRetry, func() error {
		// Get the latest version of the VLLMRouter
		latestRouter := &servingv1alpha1.VLLMRouter{}
		if err := r.Get(ctx, types.NamespacedName{Name: router.Name, Namespace: router.Namespace}, latestRouter); err != nil {
			return err
		}

		// Update the status fields
		latestRouter.Status.LastUpdated = metav1.Now()

		// Update VLLMRouter status based on deployment status
		if dep.Status.AvailableReplicas > 0 {
			latestRouter.Status.Status = "Ready"
		} else if dep.Status.UpdatedReplicas > 0 {
			latestRouter.Status.Status = "Updating"
		} else {
			latestRouter.Status.Status = "NotReady"
		}

		return r.Status().Update(ctx, latestRouter)
	})
}

// serviceForVLLMRouter returns a VLLMRouter Service object
func (r *VLLMRouterReconciler) serviceForVLLMRouter(router *servingv1alpha1.VLLMRouter) *corev1.Service {
	labels := map[string]string{
		"app": router.Name,
	}

	svc := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      router.Name,
			Namespace: router.Namespace,
		},
		Spec: corev1.ServiceSpec{
			Type:     corev1.ServiceTypeClusterIP,
			Selector: labels,
			Ports: []corev1.ServicePort{
				{
					Name:       "http",
					Port:       80,
					TargetPort: intstr.FromInt32(router.Spec.Port),
					Protocol:   corev1.ProtocolTCP,
				},
			},
		},
	}

	// Set the owner reference
	ctrl.SetControllerReference(router, svc, r.Scheme)
	return svc
}

// SetupWithManager sets up the controller with the Manager.
func (r *VLLMRouterReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&servingv1alpha1.VLLMRouter{}).
		Owns(&appsv1.Deployment{}).
		Owns(&corev1.Service{}).
		Complete(r)
}
