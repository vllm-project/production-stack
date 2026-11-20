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
	"encoding/json"
	"testing"

	v1alpha1 "production-stack/api/v1alpha1"
)

func kvEventsRuntime(port int32, topic string) *v1alpha1.VLLMRuntime {
	vr := mpRuntime()
	vr.Spec.VLLMConfig.EnablePrefixCaching = true
	vr.Spec.VLLMConfig.KVEvents = &v1alpha1.KVEventsConfig{Enabled: true, Port: port, Topic: topic}
	return vr
}

// TestKVEventsConfigArg checks the engine publishes KV events on the
// configured port, binding every interface so the router can reach the pod IP.
func TestKVEventsConfigArg(t *testing.T) {
	r := &VLLMRuntimeReconciler{Scheme: newTestScheme()}
	dep := r.deploymentForVLLMRuntime(kvEventsRuntime(0, "kv"))
	c := dep.Spec.Template.Spec.Containers[0]

	raw := flagValue(c.Args, "--kv-events-config")
	if raw == "" {
		t.Fatalf("--kv-events-config not rendered: %v", c.Args)
	}
	var cfg map[string]any
	if err := json.Unmarshal([]byte(raw), &cfg); err != nil {
		t.Fatalf("--kv-events-config is not JSON: %q", raw)
	}
	if cfg["enable_kv_cache_events"] != true || cfg["publisher"] != "zmq" ||
		cfg["endpoint"] != "tcp://*:5557" || cfg["topic"] != "kv" {
		t.Errorf("unexpected kv events config %v", cfg)
	}
	if len(c.Ports) != 2 || c.Ports[0].Name != "http" ||
		c.Ports[1].Name != "kv-events" || c.Ports[1].ContainerPort != 5557 {
		t.Errorf("unexpected container ports %v", c.Ports)
	}
}

// TestKVEventsOffByDefault checks nothing is rendered without kvEvents.
func TestKVEventsOffByDefault(t *testing.T) {
	r := &VLLMRuntimeReconciler{Scheme: newTestScheme()}
	for _, vr := range []*v1alpha1.VLLMRuntime{mpRuntime(), func() *v1alpha1.VLLMRuntime {
		vr := kvEventsRuntime(5600, "")
		vr.Spec.VLLMConfig.KVEvents.Enabled = false
		return vr
	}()} {
		c := r.deploymentForVLLMRuntime(vr).Spec.Template.Spec.Containers[0]
		if containsArg(c.Args, "--kv-events-config") || len(c.Ports) != 1 {
			t.Errorf("kv events rendered while disabled: args %v ports %v", c.Args, c.Ports)
		}
	}
}

// TestKVEventsExtraArgsWin checks a --kv-events-config in extraArgs, as
// "--flag value" or "--flag=value", is not duplicated or overridden.
func TestKVEventsExtraArgsWin(t *testing.T) {
	const userCfg = `{"enable_kv_cache_events":true}`
	for name, extra := range map[string][]string{
		"separate":   {"--kv-events-config", userCfg},
		"equals":     {"--kv-events-config=" + userCfg},
		"underscore": {"--kv_events_config", userCfg},
	} {
		t.Run(name, func(t *testing.T) {
			r := &VLLMRuntimeReconciler{Scheme: newTestScheme()}
			vr := kvEventsRuntime(5600, "")
			vr.Spec.VLLMConfig.ExtraArgs = extra
			c := r.deploymentForVLLMRuntime(vr).Spec.Template.Spec.Containers[0]
			n := 0
			for _, a := range c.Args {
				if hasFlag([]string{a}, "--kv-events-config") {
					n++
				}
			}
			if n != 1 || flagValue(c.Args, "--kv-events-config") != userCfg {
				t.Errorf("extraArgs --kv-events-config not kept as the only one: %v", c.Args)
			}
		})
	}
}

// TestKVEventsDrift checks enabling or retuning KV events rolls the pods,
// and that an unchanged runtime does not.
func TestKVEventsDrift(t *testing.T) {
	r := &VLLMRuntimeReconciler{Scheme: newTestScheme()}
	ctx := context.Background()

	stored := roundTrip(t, r.deploymentForVLLMRuntime(kvEventsRuntime(5557, "")))
	if r.deploymentNeedsUpdate(ctx, stored, kvEventsRuntime(5557, "")) {
		t.Error("unchanged kv events runtime reported as drift")
	}
	if !r.deploymentNeedsUpdate(ctx, stored, kvEventsRuntime(5600, "")) {
		t.Error("kv events port change not detected")
	}
	if !r.deploymentNeedsUpdate(ctx, stored, mpRuntime()) {
		t.Error("disabling kv events not detected")
	}
	off := roundTrip(t, r.deploymentForVLLMRuntime(mpRuntime()))
	if !r.deploymentNeedsUpdate(ctx, off, kvEventsRuntime(5557, "")) {
		t.Error("enabling kv events not detected")
	}
}

// TestRouterKVEventsArgs checks the router is pointed at the engines' port
// and topic only for kvevents routing.
func TestRouterKVEventsArgs(t *testing.T) {
	r := &VLLMRouterReconciler{Scheme: newTestScheme()}
	router := buildTestRouter("kvevents", "x-user-id", 0)
	router.Spec.KVEventsPort = 5600
	router.Spec.KVEventsTopic = "kv"
	args := r.deploymentForVLLMRouter(router).Spec.Template.Spec.Containers[0].Args
	if !containsConsecutive(args, "--routing-logic", "kvevents") ||
		!containsConsecutive(args, "--kv-events-port", "5600") ||
		!containsConsecutive(args, "--kv-events-topic", "kv") {
		t.Errorf("kvevents router args missing: %v", args)
	}

	router.Spec.RoutingLogic = "session"
	args = r.deploymentForVLLMRouter(router).Spec.Template.Spec.Containers[0].Args
	if containsArg(args, "--kv-events-port") || containsArg(args, "--kv-events-topic") {
		t.Errorf("kv events args rendered for session routing: %v", args)
	}
}
