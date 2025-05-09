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

	productionstackv1alpha1 "production-stack/api/v1alpha1"
)

// CacheServerReconciler reconciles a CacheServer object
type CacheServerReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

// +kubebuilder:rbac:groups=production-stack.vllm.ai,resources=cacheservers,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=production-stack.vllm.ai,resources=cacheservers/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=production-stack.vllm.ai,resources=cacheservers/finalizers,verbs=update
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=services,verbs=get;list;watch;create;update;patch;delete

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
func (r *CacheServerReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := log.FromContext(ctx)

	// Fetch the CacheServer instance
	cacheServer := &productionstackv1alpha1.CacheServer{}
	err := r.Get(ctx, req.NamespacedName, cacheServer)
	if err != nil {
		if errors.IsNotFound(err) {
			// Request object not found, could have been deleted after reconcile request.
			// Return and don't requeue
			log.Info("CacheServer resource not found. Ignoring since object must be deleted")
			return ctrl.Result{}, nil
		}
		// Error reading the object - requeue the request.
		log.Error(err, "Failed to get CacheServer")
		return ctrl.Result{}, err
	}

	// Check if the service already exists, if not create a new one
	foundService := &corev1.Service{}
	err = r.Get(ctx, types.NamespacedName{Name: cacheServer.Name, Namespace: cacheServer.Namespace}, foundService)
	if err != nil && errors.IsNotFound(err) {
		// Define a new service
		svc := r.serviceForCacheServer(cacheServer)
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
	err = r.Get(ctx, types.NamespacedName{Name: cacheServer.Name, Namespace: cacheServer.Namespace}, found)
	if err != nil && errors.IsNotFound(err) {
		// Define a new deployment
		dep := r.deploymentForCacheServer(cacheServer)
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
	if r.deploymentNeedsUpdate(found, cacheServer) {
		log.Info("Updating Deployment", "Deployment.Namespace", found.Namespace, "Deployment.Name", found.Name)
		// Create new deployment spec
		newDep := r.deploymentForCacheServer(cacheServer)

		err = r.Update(ctx, newDep)
		if err != nil {
			log.Error(err, "Failed to update Deployment", "Deployment.Namespace", found.Namespace, "Deployment.Name", found.Name)
			return ctrl.Result{}, err
		}
		// Deployment updated successfully - return and requeue
		return ctrl.Result{Requeue: true}, nil
	}

	// Update the status
	if err := r.updateStatus(ctx, cacheServer, found); err != nil {
		log.Error(err, "Failed to update CacheServer status")
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, nil
}

// deploymentForCacheServer returns a CacheServer Deployment object
func (r *CacheServerReconciler) deploymentForCacheServer(cacheServer *productionstackv1alpha1.CacheServer) *appsv1.Deployment {
	labels := map[string]string{
		"app": cacheServer.Name,
	}

	// Build resource requirements
	resources := corev1.ResourceRequirements{
		Requests: corev1.ResourceList{},
		Limits:   corev1.ResourceList{},
	}

	if cacheServer.Spec.Resources.CPU != "" {
		resources.Requests[corev1.ResourceCPU] = resource.MustParse(cacheServer.Spec.Resources.CPU)
		resources.Limits[corev1.ResourceCPU] = resource.MustParse(cacheServer.Spec.Resources.CPU)
	}

	if cacheServer.Spec.Resources.Memory != "" {
		resources.Requests[corev1.ResourceMemory] = resource.MustParse(cacheServer.Spec.Resources.Memory)
		resources.Limits[corev1.ResourceMemory] = resource.MustParse(cacheServer.Spec.Resources.Memory)
	}

	// Get the image from Image spec
	image := cacheServer.Spec.Image.Registry + "/" + cacheServer.Spec.Image.Name

	// Get the image pull policy
	imagePullPolicy := corev1.PullIfNotPresent
	if cacheServer.Spec.Image.PullPolicy != "" {
		imagePullPolicy = corev1.PullPolicy(cacheServer.Spec.Image.PullPolicy)
	}

	dep := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      cacheServer.Name,
			Namespace: cacheServer.Namespace,
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &cacheServer.Spec.Replicas,
			Selector: &metav1.LabelSelector{
				MatchLabels: labels,
			},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
				},
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{
						{
							Name:            "cache-server",
							Image:           image,
							ImagePullPolicy: imagePullPolicy,
							Command: []string{
								"lmcache_experimental_server",
								"0.0.0.0",
								fmt.Sprintf("%d", cacheServer.Spec.Port)},
							Ports: []corev1.ContainerPort{
								{
									Name:          "http",
									ContainerPort: cacheServer.Spec.Port,
								},
							},
							Resources: resources,
						},
					},
				},
			},
		},
	}

	// Set the owner reference
	ctrl.SetControllerReference(cacheServer, dep, r.Scheme)
	return dep
}

// deploymentNeedsUpdate checks if the deployment needs to be updated
func (r *CacheServerReconciler) deploymentNeedsUpdate(dep *appsv1.Deployment, cs *productionstackv1alpha1.CacheServer) bool {
	// Compare replicas
	if *dep.Spec.Replicas != cs.Spec.Replicas {
		return true
	}

	// Compare resources
	expectedResources := r.deploymentForCacheServer(cs).Spec.Template.Spec.Containers[0].Resources
	actualResources := dep.Spec.Template.Spec.Containers[0].Resources
	if !reflect.DeepEqual(expectedResources, actualResources) {
		return true
	}

	return false
}

// updateStatus updates the status of the CacheServer
func (r *CacheServerReconciler) updateStatus(ctx context.Context, cs *productionstackv1alpha1.CacheServer, dep *appsv1.Deployment) error {
	return retry.RetryOnConflict(retry.DefaultRetry, func() error {
		// Get the latest version of the CacheServer
		latestCS := &productionstackv1alpha1.CacheServer{}
		if err := r.Get(ctx, types.NamespacedName{Name: cs.Name, Namespace: cs.Namespace}, latestCS); err != nil {
			return err
		}

		// Update the status fields
		latestCS.Status.LastUpdated = metav1.Now()

		// Update status based on deployment status
		if dep.Status.AvailableReplicas > 0 {
			latestCS.Status.Status = "Ready"
		} else if dep.Status.UpdatedReplicas > 0 {
			latestCS.Status.Status = "Updating"
		} else {
			latestCS.Status.Status = "NotReady"
		}

		return r.Status().Update(ctx, latestCS)
	})
}

// serviceForCacheServer returns a CacheServer Service object
func (r *CacheServerReconciler) serviceForCacheServer(cacheServer *productionstackv1alpha1.CacheServer) *corev1.Service {
	labels := map[string]string{
		"app": cacheServer.Name,
	}

	svc := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      cacheServer.Name,
			Namespace: cacheServer.Namespace,
		},
		Spec: corev1.ServiceSpec{
			Type:     corev1.ServiceTypeClusterIP,
			Selector: labels,
			Ports: []corev1.ServicePort{
				{
					Name:       "http",
					Port:       80,
					TargetPort: intstr.FromInt(int(cacheServer.Spec.Port)),
					Protocol:   corev1.ProtocolTCP,
				},
			},
		},
	}

	// Set the owner reference
	ctrl.SetControllerReference(cacheServer, svc, r.Scheme)
	return svc
}

// SetupWithManager sets up the controller with the Manager.
func (r *CacheServerReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&productionstackv1alpha1.CacheServer{}).
		Owns(&appsv1.Deployment{}).
		Owns(&corev1.Service{}).
		Complete(r)
}
