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
	"testing"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"

	v1alpha1 "production-stack/api/v1alpha1"
)

func newTestScheme() *runtime.Scheme {
	s := runtime.NewScheme()
	_ = clientgoscheme.AddToScheme(s)
	_ = v1alpha1.AddToScheme(s)
	return s
}

// containsConsecutive reports whether args contains a and b as adjacent elements.
func containsConsecutive(args []string, a, b string) bool {
	for i := 0; i+1 < len(args); i++ {
		if args[i] == a && args[i+1] == b {
			return true
		}
	}
	return false
}

// containsArg reports whether arg appears anywhere in args.
func containsArg(args []string, arg string) bool {
	for _, a := range args {
		if a == arg {
			return true
		}
	}
	return false
}

// buildTestRouter constructs a minimal VLLMRouter with static service discovery.
func buildTestRouter(routingLogic, sessionKey string, lmcachePort int32) *v1alpha1.VLLMRouter {
	return &v1alpha1.VLLMRouter{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-router",
			Namespace: "default",
		},
		Spec: v1alpha1.VLLMRouterSpec{
			Replicas:              1,
			ServiceDiscovery:      "static",
			StaticBackends:        "http://backend:8000",
			StaticModels:          "test-model",
			Port:                  80,
			RoutingLogic:          routingLogic,
			SessionKey:            sessionKey,
			LmcacheControllerPort: lmcachePort,
			Image: v1alpha1.ImageSpec{
				Registry: "docker.io",
				Name:     "vllm/router:latest",
			},
		},
	}
}

func TestDeploymentNeedsUpdate(t *testing.T) {
	r := &VLLMRouterReconciler{Scheme: newTestScheme()}

	base := buildTestRouter("roundrobin", "", 0)
	dep := r.deploymentForVLLMRouter(base)

	// identical spec → no update
	if r.deploymentNeedsUpdate(dep, base) {
		t.Error("expected no update for identical spec")
	}

	// routing logic changed → args differ → update required
	changed := buildTestRouter("prefixaware", "", 0)
	if !r.deploymentNeedsUpdate(dep, changed) {
		t.Error("expected update when routingLogic changes")
	}

	// kvaware with port added → args differ → update required
	withPort := buildTestRouter("kvaware", "", 9000)
	if !r.deploymentNeedsUpdate(dep, withPort) {
		t.Error("expected update when lmcacheControllerPort added")
	}
}

func TestDeploymentArgsRouting(t *testing.T) {
	r := &VLLMRouterReconciler{Scheme: newTestScheme()}

	tests := []struct {
		name         string
		routingLogic string
		sessionKey   string
		lmcachePort  int32
		wantPresent  [][2]string // pairs that must appear consecutively
		wantAbsent   []string    // flags that must not appear
	}{
		{
			name:         "roundrobin",
			routingLogic: "roundrobin",
			wantPresent:  [][2]string{{"--routing-logic", "roundrobin"}},
			wantAbsent:   []string{"--lmcache-controller-port"},
		},
		{
			name:         "session with key",
			routingLogic: "session",
			sessionKey:   "mykey",
			wantPresent: [][2]string{
				{"--routing-logic", "session"},
				{"--session-key", "mykey"},
			},
			wantAbsent: []string{"--lmcache-controller-port"},
		},
		{
			name:         "prefixaware",
			routingLogic: "prefixaware",
			wantPresent:  [][2]string{{"--routing-logic", "prefixaware"}},
			wantAbsent:   []string{"--lmcache-controller-port"},
		},
		{
			name:         "kvaware default port",
			routingLogic: "kvaware",
			lmcachePort:  9000,
			wantPresent: [][2]string{
				{"--routing-logic", "kvaware"},
				{"--lmcache-controller-port", "9000"},
			},
		},
		{
			name:         "kvaware custom port",
			routingLogic: "kvaware",
			lmcachePort:  8888,
			wantPresent: [][2]string{
				{"--routing-logic", "kvaware"},
				{"--lmcache-controller-port", "8888"},
			},
		},
		{
			name:         "kvaware zero port",
			routingLogic: "kvaware",
			lmcachePort:  0,
			wantPresent:  [][2]string{{"--routing-logic", "kvaware"}},
			wantAbsent:   []string{"--lmcache-controller-port"},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			router := buildTestRouter(tc.routingLogic, tc.sessionKey, tc.lmcachePort)
			dep := r.deploymentForVLLMRouter(router)

			if dep == nil {
				t.Fatal("deploymentForVLLMRouter returned nil")
			}
			if len(dep.Spec.Template.Spec.Containers) == 0 {
				t.Fatal("deployment has no containers")
			}

			args := dep.Spec.Template.Spec.Containers[0].Args

			for _, pair := range tc.wantPresent {
				if !containsConsecutive(args, pair[0], pair[1]) {
					t.Errorf("expected args to contain %q %q, got: %v", pair[0], pair[1], args)
				}
			}

			for _, flag := range tc.wantAbsent {
				if containsArg(args, flag) {
					t.Errorf("expected args NOT to contain %q, got: %v", flag, args)
				}
			}
		})
	}
}
