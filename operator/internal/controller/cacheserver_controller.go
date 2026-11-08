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
	"k8s.io/apimachinery/pkg/api/equality"
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

	// Keep the Service ports in step with spec.port and multiprocess.httpPort,
	// including Services created by an older operator that published port 80.
	if expectedPorts := cacheServerServicePorts(cacheServer); servicePortsDiffer(foundService.Spec.Ports, expectedPorts) {
		log.Info("Updating Service ports", "Service.Namespace", foundService.Namespace, "Service.Name", foundService.Name)
		foundService.Spec.Ports = expectedPorts
		if err := r.Update(ctx, foundService); err != nil {
			log.Error(err, "Failed to update Service", "Service.Namespace", foundService.Namespace, "Service.Name", foundService.Name)
			return ctrl.Result{}, err
		}
		return ctrl.Result{Requeue: true}, nil
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

// cacheServerCommand builds the `lmcache server` command for a CacheServer
// from Spec.Multiprocess. The server always binds 0.0.0.0 so the Service can
// reach it from other pods.
func cacheServerCommand(cs *productionstackv1alpha1.CacheServer) []string {
	mp := cs.Spec.Multiprocess

	// --l1-size-gb and --eviction-policy are required by the server, so fall
	// back to the API defaults when a spec was built without them.
	l1SizeGB := mp.L1SizeGB
	if l1SizeGB <= 0 {
		l1SizeGB = 10
	}
	evictionPolicy := mp.EvictionPolicy
	if evictionPolicy == "" {
		evictionPolicy = "LRU"
	}
	chunkSize := mp.ChunkSize
	if chunkSize <= 0 {
		chunkSize = 256
	}

	cmd := []string{
		"/opt/venv/bin/lmcache",
		"server",
		"--host", "0.0.0.0",
		"--port", fmt.Sprintf("%d", cs.Spec.Port),
		"--l1-size-gb", fmt.Sprintf("%d", l1SizeGB),
		"--eviction-policy", evictionPolicy,
		"--chunk-size", fmt.Sprintf("%d", chunkSize),
	}

	cmd = append(cmd, "--supported-transfer-mode", mpTransferMode(mp.TransferMode))
	if mp.HTTPPort > 0 {
		cmd = append(cmd, "--http-port", fmt.Sprintf("%d", mp.HTTPPort))
	}
	if mp.L1InitSizeGB > 0 {
		cmd = append(cmd, "--l1-init-size-gb", fmt.Sprintf("%d", mp.L1InitSizeGB))
	}
	if mp.L1AlignBytes > 0 {
		cmd = append(cmd, "--l1-align-bytes", fmt.Sprintf("%d", mp.L1AlignBytes))
	}
	if mp.EvictionTriggerWatermark != "" {
		cmd = append(cmd, "--eviction-trigger-watermark", mp.EvictionTriggerWatermark)
	}
	if mp.EvictionRatio != "" {
		cmd = append(cmd, "--eviction-ratio", mp.EvictionRatio)
	}
	for _, adapter := range mp.L2Adapters {
		cmd = append(cmd, "--l2-adapter", adapter)
	}
	if mp.MaxWorkers > 0 {
		cmd = append(cmd, "--max-workers", fmt.Sprintf("%d", mp.MaxWorkers))
	}
	if mp.MaxGPUWorkers > 0 {
		cmd = append(cmd, "--max-gpu-workers", fmt.Sprintf("%d", mp.MaxGPUWorkers))
	}
	if mp.MaxCPUWorkers > 0 {
		cmd = append(cmd, "--max-cpu-workers", fmt.Sprintf("%d", mp.MaxCPUWorkers))
	}
	if mp.InstanceID != "" {
		cmd = append(cmd, "--instance-id", mp.InstanceID)
	}
	// Both flags default to false on the server, so only the enabling form is
	// ever rendered.
	if mp.SeparateObjectGroups {
		cmd = append(cmd, "--separate-object-groups")
	}
	if mp.IsolatedIPC {
		cmd = append(cmd, "--isolated-ipc")
	}

	return append(cmd, mp.ExtraArgs...)
}

// cacheServerContainerPorts lists the ports the cache server container exposes:
// the ZMQ port engines connect to, and the HTTP frontend for metrics.
func cacheServerContainerPorts(cs *productionstackv1alpha1.CacheServer) []corev1.ContainerPort {
	ports := []corev1.ContainerPort{
		{
			Name:          "zmq",
			ContainerPort: cs.Spec.Port,
			Protocol:      corev1.ProtocolTCP,
		},
	}
	if cs.Spec.Multiprocess.HTTPPort > 0 {
		ports = append(ports, corev1.ContainerPort{
			Name:          "metrics",
			ContainerPort: cs.Spec.Multiprocess.HTTPPort,
			Protocol:      corev1.ProtocolTCP,
		})
	}
	return ports
}

// defaultMPTransferMode is the transfer mode rendered when a spec leaves it
// empty. It is also the API default, so this only matters for objects that
// bypassed defaulting.
const defaultMPTransferMode = "lmcache_driven"

// mpTransferMode returns mode, or the default when mode is empty.
func mpTransferMode(mode string) string {
	if mode == "" {
		return defaultMPTransferMode
	}
	return mode
}

// cacheServerEnv builds the environment for the cache server container.
func cacheServerEnv(cs *productionstackv1alpha1.CacheServer) []corev1.EnvVar {
	// nil rather than an empty slice: the API server drops an empty env list,
	// and a CacheServer with no env must compare equal to what it reads back.
	var env []corev1.EnvVar
	for _, e := range cs.Spec.Env {
		env = append(env, corev1.EnvVar{Name: e.Name, Value: e.Value})
	}
	return env
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
			Strategy: cacheServerStrategy(cacheServer),
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
				},
				Spec: corev1.PodSpec{
					HostIPC:          cacheServer.Spec.HostIPC,
					Volumes:          cacheServer.Spec.Volumes,
					RuntimeClassName: runtimeClassOrNil(cacheServer.Spec.RuntimeClassName),
					Containers: []corev1.Container{
						{
							Name:            "cache-server",
							Image:           image,
							ImagePullPolicy: imagePullPolicy,
							Command:         cacheServerCommand(cacheServer),
							Ports:           cacheServerContainerPorts(cacheServer),
							Env:             cacheServerEnv(cacheServer),
							Resources:       resources,
							VolumeMounts:    cacheServer.Spec.VolumeMounts,
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

// runtimeClassOrNil converts a RuntimeClass name into the pointer a PodSpec
// wants, mapping the empty string to nil. Passing a pointer to "" instead would
// ask the API server for a RuntimeClass literally named "", which no cluster
// has, and the pod would never be admitted.
func runtimeClassOrNil(name string) *string {
	if name == "" {
		return nil
	}
	return &name
}

// cacheServerStrategy renders spec.deploymentStrategy into a DeploymentStrategy.
//
// Recreate matters for the cache server: its L1 arena is pinned host
// memory, and a rolling update would have the new pod try to pin a second arena
// while the old one still holds the first.
func cacheServerStrategy(cs *productionstackv1alpha1.CacheServer) appsv1.DeploymentStrategy {
	if cs.Spec.DeploymentStrategy == string(appsv1.RecreateDeploymentStrategyType) {
		return appsv1.DeploymentStrategy{Type: appsv1.RecreateDeploymentStrategyType}
	}
	return appsv1.DeploymentStrategy{Type: appsv1.RollingUpdateDeploymentStrategyType}
}

// deploymentNeedsUpdate checks if the deployment needs to be updated
func (r *CacheServerReconciler) deploymentNeedsUpdate(dep *appsv1.Deployment, cs *productionstackv1alpha1.CacheServer) bool {
	// Compare replicas
	if *dep.Spec.Replicas != cs.Spec.Replicas {
		return true
	}
	// Generate the expected deployment
	expectedDep := r.deploymentForCacheServer(cs)

	// Compare image
	if len(dep.Spec.Template.Spec.Containers) > 0 &&
		expectedDep.Spec.Template.Spec.Containers[0].Image != dep.Spec.Template.Spec.Containers[0].Image {
		return true
	}

	// Compare resources
	expectedResources := expectedDep.Spec.Template.Spec.Containers[0].Resources
	actualResources := dep.Spec.Template.Spec.Containers[0].Resources
	if !reflect.DeepEqual(expectedResources, actualResources) {
		return true
	}

	// Compare the rendered server command, so a change to the mode or to any
	// multiprocess flag rolls the deployment.
	if !reflect.DeepEqual(
		expectedDep.Spec.Template.Spec.Containers[0].Command,
		dep.Spec.Template.Spec.Containers[0].Command,
	) {
		return true
	}

	// Compare environment and ports. Semantic equality, because the API server
	// returns an empty env list as nil.
	if !equality.Semantic.DeepEqual(
		expectedDep.Spec.Template.Spec.Containers[0].Env,
		dep.Spec.Template.Spec.Containers[0].Env,
	) {
		return true
	}
	if !reflect.DeepEqual(
		expectedDep.Spec.Template.Spec.Containers[0].Ports,
		dep.Spec.Template.Spec.Containers[0].Ports,
	) {
		return true
	}

	// Compare the IPC namespace.
	if expectedDep.Spec.Template.Spec.HostIPC != dep.Spec.Template.Spec.HostIPC {
		return true
	}

	// Compare storage. Semantic equality, because the API server stores an
	// empty list as nil and a plain DeepEqual would roll the deployment on
	// every reconcile.
	if !equality.Semantic.DeepEqual(
		expectedDep.Spec.Template.Spec.Volumes,
		dep.Spec.Template.Spec.Volumes,
	) {
		return true
	}
	if !equality.Semantic.DeepEqual(
		expectedDep.Spec.Template.Spec.Containers[0].VolumeMounts,
		dep.Spec.Template.Spec.Containers[0].VolumeMounts,
	) {
		return true
	}

	// Compare the RuntimeClass. A cache server under the wrong RuntimeClass
	// cannot see the engines' GPUs and falls back to StubCPUDevice in
	// lmcache_driven mode.
	if !equality.Semantic.DeepEqual(
		expectedDep.Spec.Template.Spec.RuntimeClassName,
		dep.Spec.Template.Spec.RuntimeClassName,
	) {
		return true
	}

	// Compare the update strategy.
	if expectedDep.Spec.Strategy.Type != dep.Spec.Strategy.Type {
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
		if dep.Status.AvailableReplicas == *dep.Spec.Replicas && dep.Status.UnavailableReplicas == 0 {
			latestCS.Status.Status = "Ready"
		} else if dep.Status.UpdatedReplicas > 0 && dep.Status.AvailableReplicas != *dep.Spec.Replicas && dep.Status.UnavailableReplicas > 0 {
			latestCS.Status.Status = "Updating"
		} else if dep.Status.UnavailableReplicas > 0 {
			latestCS.Status.Status = "NotReady"
		} else {
			latestCS.Status.Status = "Unknown"
		}

		return r.Status().Update(ctx, latestCS)
	})
}

// cacheServerServicePorts lists the ports the CacheServer Service publishes.
// The ZMQ port is published on its own number, so the port in the engine's
// lmcache.mp.port matches the port in the spec, and the HTTP frontend is
// published alongside it.
func cacheServerServicePorts(cs *productionstackv1alpha1.CacheServer) []corev1.ServicePort {
	ports := []corev1.ServicePort{
		{
			Name:       "zmq",
			Port:       cs.Spec.Port,
			TargetPort: intstr.FromInt32(cs.Spec.Port),
			Protocol:   corev1.ProtocolTCP,
		},
	}
	if cs.Spec.Multiprocess.HTTPPort > 0 {
		ports = append(ports, corev1.ServicePort{
			Name:       "metrics",
			Port:       cs.Spec.Multiprocess.HTTPPort,
			TargetPort: intstr.FromInt32(cs.Spec.Multiprocess.HTTPPort),
			Protocol:   corev1.ProtocolTCP,
		})
	}
	return ports
}

// servicePortsDiffer reports whether the live Service ports differ from the
// expected ones in name, port, target port or protocol. Fields the API server
// fills in, such as NodePort, are ignored.
func servicePortsDiffer(actual, expected []corev1.ServicePort) bool {
	if len(actual) != len(expected) {
		return true
	}
	for i := range expected {
		a, e := actual[i], expected[i]
		if a.Name != e.Name || a.Port != e.Port || a.TargetPort != e.TargetPort || a.Protocol != e.Protocol {
			return true
		}
	}
	return false
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
			Ports:    cacheServerServicePorts(cacheServer),
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
