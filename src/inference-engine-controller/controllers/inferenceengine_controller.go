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

package controllers

import (
	"context"
	"fmt"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/log"

	inferencev1alpha1 "github.com/vllm-project/production-stack/api/v1alpha1"
	"github.com/vllm-project/production-stack/pkg/resources"
)

// InferenceEngineReconciler reconciles a InferenceEngine object
type InferenceEngineReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

//+kubebuilder:rbac:groups=production-stack.vllm.ai,resources=inferenceengines,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=production-stack.vllm.ai,resources=inferenceengines/status,verbs=get;update;patch
//+kubebuilder:rbac:groups=production-stack.vllm.ai,resources=inferenceengines/finalizers,verbs=update
//+kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=core,resources=services,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=core,resources=persistentvolumeclaims,verbs=get;list;watch;create;update;patch;delete

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
func (r *InferenceEngineReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)
	logger.Info("Reconciling InferenceEngine", "request", req)

	// Get the InferenceEngine resource
	engine := &inferencev1alpha1.InferenceEngine{}
	if err := r.Get(ctx, req.NamespacedName, engine); err != nil {
		if errors.IsNotFound(err) {
			// Object not found, could have been deleted after reconcile request.
			logger.Info("InferenceEngine resource not found. Ignoring since object must be deleted")
			return ctrl.Result{}, nil
		}
		// Error reading the object - requeue the request.
		logger.Error(err, "Failed to get InferenceEngine")
		return ctrl.Result{}, err
	}

	// Initialize status if not set
	if engine.Status.Phase == "" {
		engine.Status.Phase = inferencev1alpha1.InferenceEnginePhasePending
		engine.Status.Message = "Initializing"
		err := r.Status().Update(ctx, engine)
		if err != nil {
			logger.Error(err, "Failed to update InferenceEngine status")
			return ctrl.Result{}, err
		}
		return ctrl.Result{Requeue: true}, nil
	}

	// Create PVC for model storage
	pvc := resources.CreatePVC(engine)
	existingPVC := &corev1.PersistentVolumeClaim{}
	err := r.Get(ctx, types.NamespacedName{Name: pvc.Name, Namespace: pvc.Namespace}, existingPVC)
	if err != nil && errors.IsNotFound(err) {
		logger.Info("Creating PVC", "name", pvc.Name)
		err = r.Create(ctx, pvc)
		if err != nil {
			logger.Error(err, "Failed to create PVC")
			r.updateStatus(ctx, engine, inferencev1alpha1.InferenceEnginePhaseFailed, fmt.Sprintf("Failed to create PVC: %v", err))
			return ctrl.Result{}, err
		}
	} else if err != nil {
		logger.Error(err, "Failed to get PVC")
		return ctrl.Result{}, err
	}

	// Create appropriate deployments and services based on the deployment mode
	if engine.Spec.DeploymentMode == "basic" {
		err = r.reconcileBasicMode(ctx, engine)
	} else if engine.Spec.DeploymentMode == "disaggregated" {
		err = r.reconcileDisaggregatedMode(ctx, engine)
	} else {
		err = fmt.Errorf("unsupported deployment mode: %s", engine.Spec.DeploymentMode)
		r.updateStatus(ctx, engine, inferencev1alpha1.InferenceEnginePhaseFailed, fmt.Sprintf("Unsupported deployment mode: %s", engine.Spec.DeploymentMode))
	}

	if err != nil {
		logger.Error(err, "Failed to reconcile deployments")
		return ctrl.Result{}, err
	}

	// Check if all deployments are ready
	isReady, err := r.checkDeploymentsReady(ctx, engine)
	if err != nil {
		logger.Error(err, "Failed to check deployment readiness")
		return ctrl.Result{}, err
	}

	if isReady {
		r.updateStatus(ctx, engine, inferencev1alpha1.InferenceEnginePhaseRunning, "All components are running")
	} else {
		r.updateStatus(ctx, engine, inferencev1alpha1.InferenceEnginePhasePending, "Waiting for all components to be ready")
	}

	// Requeue to check status
	return ctrl.Result{RequeueAfter: time.Second * 10}, nil
}

// reconcileBasicMode creates resources for basic deployment mode
func (r *InferenceEngineReconciler) reconcileBasicMode(ctx context.Context, engine *inferencev1alpha1.InferenceEngine) error {
	logger := log.FromContext(ctx)

	// Create basic deployment
	deploy := resources.CreateBasicDeployment(engine)
	existingDeploy := &appsv1.Deployment{}
	err := r.Get(ctx, types.NamespacedName{Name: deploy.Name, Namespace: deploy.Namespace}, existingDeploy)
	if err != nil && errors.IsNotFound(err) {
		logger.Info("Creating basic deployment", "name", deploy.Name)
		err = r.Create(ctx, deploy)
		if err != nil {
			logger.Error(err, "Failed to create basic deployment")
			r.updateStatus(ctx, engine, inferencev1alpha1.InferenceEnginePhaseFailed, fmt.Sprintf("Failed to create basic deployment: %v", err))
			return err
		}
	} else if err != nil {
		logger.Error(err, "Failed to get deployment")
		return err
	} else {
		// Update if needed
		existingDeploy.Spec = deploy.Spec
		logger.Info("Updating basic deployment", "name", deploy.Name)
		err = r.Update(ctx, existingDeploy)
		if err != nil {
			logger.Error(err, "Failed to update basic deployment")
			return err
		}
	}

	// Create service
	svc := resources.CreateService(engine, "basic")
	existingSvc := &corev1.Service{}
	err = r.Get(ctx, types.NamespacedName{Name: svc.Name, Namespace: svc.Namespace}, existingSvc)
	if err != nil && errors.IsNotFound(err) {
		logger.Info("Creating service", "name", svc.Name)
		err = r.Create(ctx, svc)
		if err != nil {
			logger.Error(err, "Failed to create service")
			r.updateStatus(ctx, engine, inferencev1alpha1.InferenceEnginePhaseFailed, fmt.Sprintf("Failed to create service: %v", err))
			return err
		}
	} else if err != nil {
		logger.Error(err, "Failed to get service")
		return err
	}

	return nil
}

// reconcileDisaggregatedMode creates resources for disaggregated deployment mode
func (r *InferenceEngineReconciler) reconcileDisaggregatedMode(ctx context.Context, engine *inferencev1alpha1.InferenceEngine) error {
	logger := log.FromContext(ctx)

	// Create prefill deployment
	prefillDeploy := resources.CreatePrefillDeployment(engine)
	existingPrefillDeploy := &appsv1.Deployment{}
	err := r.Get(ctx, types.NamespacedName{Name: prefillDeploy.Name, Namespace: prefillDeploy.Namespace}, existingPrefillDeploy)
	if err != nil && errors.IsNotFound(err) {
		logger.Info("Creating prefill deployment", "name", prefillDeploy.Name)
		err = r.Create(ctx, prefillDeploy)
		if err != nil {
			logger.Error(err, "Failed to create prefill deployment")
			r.updateStatus(ctx, engine, inferencev1alpha1.InferenceEnginePhaseFailed, fmt.Sprintf("Failed to create prefill deployment: %v", err))
			return err
		}
	} else if err != nil {
		logger.Error(err, "Failed to get prefill deployment")
		return err
	} else {
		// Update if needed
		existingPrefillDeploy.Spec = prefillDeploy.Spec
		logger.Info("Updating prefill deployment", "name", prefillDeploy.Name)
		err = r.Update(ctx, existingPrefillDeploy)
		if err != nil {
			logger.Error(err, "Failed to update prefill deployment")
			return err
		}
	}

	// Create prefill service
	prefillSvc := resources.CreateService(engine, "prefill")
	existingPrefillSvc := &corev1.Service{}
	err = r.Get(ctx, types.NamespacedName{Name: prefillSvc.Name, Namespace: prefillSvc.Namespace}, existingPrefillSvc)
	if err != nil && errors.IsNotFound(err) {
		logger.Info("Creating prefill service", "name", prefillSvc.Name)
		err = r.Create(ctx, prefillSvc)
		if err != nil {
			logger.Error(err, "Failed to create prefill service")
			r.updateStatus(ctx, engine, inferencev1alpha1.InferenceEnginePhaseFailed, fmt.Sprintf("Failed to create prefill service: %v", err))
			return err
		}
	} else if err != nil {
		logger.Error(err, "Failed to get prefill service")
		return err
	}

	// Create decode deployment
	decodeDeploy := resources.CreateDecodeDeployment(engine)
	existingDecodeDeploy := &appsv1.Deployment{}
	err = r.Get(ctx, types.NamespacedName{Name: decodeDeploy.Name, Namespace: decodeDeploy.Namespace}, existingDecodeDeploy)
	if err != nil && errors.IsNotFound(err) {
		logger.Info("Creating decode deployment", "name", decodeDeploy.Name)
		err = r.Create(ctx, decodeDeploy)
		if err != nil {
			logger.Error(err, "Failed to create decode deployment")
			r.updateStatus(ctx, engine, inferencev1alpha1.InferenceEnginePhaseFailed, fmt.Sprintf("Failed to create decode deployment: %v", err))
			return err
		}
	} else if err != nil {
		logger.Error(err, "Failed to get decode deployment")
		return err
	} else {
		// Update if needed
		existingDecodeDeploy.Spec = decodeDeploy.Spec
		logger.Info("Updating decode deployment", "name", decodeDeploy.Name)
		err = r.Update(ctx, existingDecodeDeploy)
		if err != nil {
			logger.Error(err, "Failed to update decode deployment")
			return err
		}
	}

	// Create decode service
	decodeSvc := resources.CreateService(engine, "decode")
	existingDecodeSvc := &corev1.Service{}
	err = r.Get(ctx, types.NamespacedName{Name: decodeSvc.Name, Namespace: decodeSvc.Namespace}, existingDecodeSvc)
	if err != nil && errors.IsNotFound(err) {
		logger.Info("Creating decode service", "name", decodeSvc.Name)
		err = r.Create(ctx, decodeSvc)
		if err != nil {
			logger.Error(err, "Failed to create decode service")
			r.updateStatus(ctx, engine, inferencev1alpha1.InferenceEnginePhaseFailed, fmt.Sprintf("Failed to create decode service: %v", err))
			return err
		}
	} else if err != nil {
		logger.Error(err, "Failed to get decode service")
		return err
	}

	// Create proxy deployment if enabled
	if engine.Spec.DisaggregationConfig != nil && engine.Spec.DisaggregationConfig.ProxyConfig != nil {
		proxyDeploy := resources.CreateProxyDeployment(engine)
		if proxyDeploy != nil {
			existingProxyDeploy := &appsv1.Deployment{}
			err = r.Get(ctx, types.NamespacedName{Name: proxyDeploy.Name, Namespace: proxyDeploy.Namespace}, existingProxyDeploy)
			if err != nil && errors.IsNotFound(err) {
				logger.Info("Creating proxy deployment", "name", proxyDeploy.Name)
				err = r.Create(ctx, proxyDeploy)
				if err != nil {
					logger.Error(err, "Failed to create proxy deployment")
					r.updateStatus(ctx, engine, inferencev1alpha1.InferenceEnginePhaseFailed, fmt.Sprintf("Failed to create proxy deployment: %v", err))
					return err
				}
			} else if err != nil {
				logger.Error(err, "Failed to get proxy deployment")
				return err
			} else {
				// Update if needed
				existingProxyDeploy.Spec = proxyDeploy.Spec
				logger.Info("Updating proxy deployment", "name", proxyDeploy.Name)
				err = r.Update(ctx, existingProxyDeploy)
				if err != nil {
					logger.Error(err, "Failed to update proxy deployment")
					return err
				}
			}

			// Create proxy service
			proxySvc := resources.CreateService(engine, "proxy")
			existingProxySvc := &corev1.Service{}
			err = r.Get(ctx, types.NamespacedName{Name: proxySvc.Name, Namespace: proxySvc.Namespace}, existingProxySvc)
			if err != nil && errors.IsNotFound(err) {
				logger.Info("Creating proxy service", "name", proxySvc.Name)
				err = r.Create(ctx, proxySvc)
				if err != nil {
					logger.Error(err, "Failed to create proxy service")
					r.updateStatus(ctx, engine, inferencev1alpha1.InferenceEnginePhaseFailed, fmt.Sprintf("Failed to create proxy service: %v", err))
					return err
				}
			} else if err != nil {
				logger.Error(err, "Failed to get proxy service")
				return err
			}
		}
	}

	return nil
}

// checkDeploymentsReady checks if all deployments are ready
func (r *InferenceEngineReconciler) checkDeploymentsReady(ctx context.Context, engine *inferencev1alpha1.InferenceEngine) (bool, error) {
	logger := log.FromContext(ctx)

	if engine.Spec.DeploymentMode == "basic" {
		// Check basic deployment
		deploy := &appsv1.Deployment{}
		err := r.Get(ctx, types.NamespacedName{Name: engine.Name, Namespace: engine.Namespace}, deploy)
		if err != nil {
			logger.Error(err, "Failed to get basic deployment")
			return false, err
		}

		if deploy.Status.ReadyReplicas != *deploy.Spec.Replicas {
			logger.Info("Basic deployment not ready yet", "ready", deploy.Status.ReadyReplicas, "desired", *deploy.Spec.Replicas)
			return false, nil
		}

		return true, nil
	} else if engine.Spec.DeploymentMode == "disaggregated" {
		// Check prefill deployment
		prefillDeploy := &appsv1.Deployment{}
		err := r.Get(ctx, types.NamespacedName{Name: fmt.Sprintf("%s-prefill", engine.Name), Namespace: engine.Namespace}, prefillDeploy)
		if err != nil {
			logger.Error(err, "Failed to get prefill deployment")
			return false, err
		}

		if prefillDeploy.Status.ReadyReplicas != *prefillDeploy.Spec.Replicas {
			logger.Info("Prefill deployment not ready yet", "ready", prefillDeploy.Status.ReadyReplicas, "desired", *prefillDeploy.Spec.Replicas)
			return false, nil
		}

		// Check decode deployment
		decodeDeploy := &appsv1.Deployment{}
		err = r.Get(ctx, types.NamespacedName{Name: fmt.Sprintf("%s-decode", engine.Name), Namespace: engine.Namespace}, decodeDeploy)
		if err != nil {
			logger.Error(err, "Failed to get decode deployment")
			return false, err
		}

		if decodeDeploy.Status.ReadyReplicas != *decodeDeploy.Spec.Replicas {
			logger.Info("Decode deployment not ready yet", "ready", decodeDeploy.Status.ReadyReplicas, "desired", *decodeDeploy.Spec.Replicas)
			return false, nil
		}

		// Check proxy deployment if enabled
		if engine.Spec.DisaggregationConfig != nil && engine.Spec.DisaggregationConfig.ProxyConfig != nil {
			proxyDeploy := &appsv1.Deployment{}
			err = r.Get(ctx, types.NamespacedName{Name: fmt.Sprintf("%s-proxy", engine.Name), Namespace: engine.Namespace}, proxyDeploy)
			if err != nil {
				logger.Error(err, "Failed to get proxy deployment")
				return false, err
			}

			if proxyDeploy.Status.ReadyReplicas != *proxyDeploy.Spec.Replicas {
				logger.Info("Proxy deployment not ready yet", "ready", proxyDeploy.Status.ReadyReplicas, "desired", *proxyDeploy.Spec.Replicas)
				return false, nil
			}
		}

		return true, nil
	}

	return false, fmt.Errorf("unsupported deployment mode: %s", engine.Spec.DeploymentMode)
}

// updateStatus updates the status of the InferenceEngine
func (r *InferenceEngineReconciler) updateStatus(ctx context.Context, engine *inferencev1alpha1.InferenceEngine, phase inferencev1alpha1.InferenceEnginePhase, message string) {
	logger := log.FromContext(ctx)

	// Get the latest version of the resource
	latest := &inferencev1alpha1.InferenceEngine{}
	if err := r.Get(ctx, types.NamespacedName{Name: engine.Name, Namespace: engine.Namespace}, latest); err != nil {
		logger.Error(err, "Failed to get latest InferenceEngine")
		return
	}

	// Update status
	latest.Status.Phase = phase
	latest.Status.Message = message

	// Update conditions
	now := metav1.Now()
	condition := metav1.Condition{
		Type:               string(phase),
		Status:             metav1.ConditionTrue,
		Reason:             string(phase),
		Message:            message,
		LastTransitionTime: now,
	}

	// Find and update existing condition or add a new one
	found := false
	for i, c := range latest.Status.Conditions {
		if c.Type == condition.Type {
			latest.Status.Conditions[i] = condition
			found = true
			break
		}
	}

	if !found {
		latest.Status.Conditions = append(latest.Status.Conditions, condition)
	}

	if err := r.Status().Update(ctx, latest); err != nil {
		logger.Error(err, "Failed to update InferenceEngine status")
	}
}

// SetupWithManager sets up the controller with the Manager.
func (r *InferenceEngineReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&inferencev1alpha1.InferenceEngine{}).
		Owns(&appsv1.Deployment{}).
		Owns(&corev1.Service{}).
		Owns(&corev1.PersistentVolumeClaim{}).
		Complete(r)
}
