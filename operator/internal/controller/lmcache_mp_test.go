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
	"encoding/json"
	"reflect"
	"strings"
	"testing"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/util/intstr"

	productionstackv1alpha1 "production-stack/api/v1alpha1"
)

// mpCacheServer builds a CacheServer with the settings verified against a
// hybrid model.
func mpCacheServer() *productionstackv1alpha1.CacheServer {
	return &productionstackv1alpha1.CacheServer{
		Spec: productionstackv1alpha1.CacheServerSpec{
			Port: 9000,
			Multiprocess: productionstackv1alpha1.MultiprocessSpec{
				TransferMode:         "lmcache_driven",
				L1SizeGB:             32,
				EvictionPolicy:       "LRU",
				ChunkSize:            1056,
				HTTPPort:             8082,
				L1AlignBytes:         4096,
				SeparateObjectGroups: true,
				L2Adapters: []string{
					`{"type":"fs_native","base_path":"/mnt/kvcache"}`,
				},
			},
		},
	}
}

func TestCacheServerCommandMultiprocess(t *testing.T) {
	want := []string{
		"/opt/venv/bin/lmcache", "server",
		"--host", "0.0.0.0",
		"--port", "9000",
		"--l1-size-gb", "32",
		"--eviction-policy", "LRU",
		"--chunk-size", "1056",
		"--supported-transfer-mode", "lmcache_driven",
		"--http-port", "8082",
		"--l1-align-bytes", "4096",
		"--l2-adapter", `{"type":"fs_native","base_path":"/mnt/kvcache"}`,
		"--separate-object-groups",
	}
	if got := cacheServerCommand(mpCacheServer()); !reflect.DeepEqual(got, want) {
		t.Errorf("multiprocess command:\n got %v\nwant %v", got, want)
	}
}

func TestCacheServerCommandRendersRequiredFlagsWhenUnset(t *testing.T) {
	// --l1-size-gb and --eviction-policy are required by the server, so they
	// must appear even when a spec bypasses the API defaults.
	cs := &productionstackv1alpha1.CacheServer{
		Spec: productionstackv1alpha1.CacheServerSpec{Port: 5555},
	}

	got := cacheServerCommand(cs)
	// A bare spec still runs the multiprocess server: the legacy
	// lmcache_server binary is gone from LMCache 0.5.7rc2 onwards.
	if len(got) < 2 || got[0] != "/opt/venv/bin/lmcache" || got[1] != "server" {
		t.Fatalf("bare spec does not run `lmcache server`: %v", got)
	}
	if v := argValue(got, "--l1-size-gb"); v != "10" {
		t.Errorf("--l1-size-gb fallback = %q, want 10", v)
	}
	for _, flag := range []string{"--l1-size-gb", "--eviction-policy", "--chunk-size"} {
		if !containsArg(got, flag) {
			t.Errorf("required flag %s missing from %v", flag, got)
		}
	}
	// The transfer mode is always pinned to lmcache_driven rather than left to
	// the server's own default.
	if mode := argValue(got, "--supported-transfer-mode"); mode != "lmcache_driven" {
		t.Errorf("--supported-transfer-mode = %q, want lmcache_driven", mode)
	}
	// Booleans default to false on the server, so the flags must stay off.
	for _, flag := range []string{"--separate-object-groups", "--isolated-ipc"} {
		if containsArg(got, flag) {
			t.Errorf("flag %s rendered while disabled: %v", flag, got)
		}
	}
}

func TestCacheServerCommandOptionalFlags(t *testing.T) {
	cs := mpCacheServer()
	cs.Spec.Multiprocess.IsolatedIPC = true
	cs.Spec.Multiprocess.MaxWorkers = 4
	cs.Spec.Multiprocess.InstanceID = "cache-a"
	cs.Spec.Multiprocess.ExtraArgs = []string{"--enable", "transfer_query"}

	got := cacheServerCommand(cs)
	for _, flag := range []string{
		"--isolated-ipc", "--max-workers", "--instance-id",
	} {
		if !containsArg(got, flag) {
			t.Errorf("flag %s missing from %v", flag, got)
		}
	}
	// ExtraArgs are appended last so they can override earlier flags.
	if n := len(got); got[n-2] != "--enable" || got[n-1] != "transfer_query" {
		t.Errorf("extraArgs not appended last: %v", got)
	}
}

func TestCacheServerEnvKeepsUserValues(t *testing.T) {
	cs := mpCacheServer()
	cs.Spec.Env = []productionstackv1alpha1.EnvVar{
		{Name: "LMCACHE_LOG_LEVEL", Value: "DEBUG"},
	}

	env := cacheServerEnv(cs)
	last := env[len(env)-1]
	if last.Name != "LMCACHE_LOG_LEVEL" || last.Value != "DEBUG" {
		t.Errorf("user env not appended last: %v", env)
	}
}

func TestCacheServerServicePorts(t *testing.T) {
	// The ZMQ port is published on its own number, so the engine's
	// lmcache.mp.port matches the spec.
	ports := cacheServerServicePorts(mpCacheServer())
	if len(ports) != 2 {
		t.Fatalf("want zmq and metrics ports, got %+v", ports)
	}
	if ports[0].Port != 9000 {
		t.Errorf("zmq port = %d, want 9000", ports[0].Port)
	}
	if ports[1].Port != 8082 {
		t.Errorf("metrics port = %d, want 8082", ports[1].Port)
	}
}

// TestLMCacheKVTransferConfigInProcessMatchesMain checks InProcess mode renders
// byte for byte the document main always rendered, so a runtime upgraded from
// main sees no kv-transfer-config drift and does not roll.
func TestLMCacheKVTransferConfigInProcessMatchesMain(t *testing.T) {
	for _, tc := range []struct {
		v1   bool
		want string
	}{
		{true, `{"kv_connector":"LMCacheConnectorV1","kv_role":"kv_both"}`},
		{false, `{"kv_connector":"LMCacheConnector","kv_role":"kv_both"}`},
	} {
		vr := &productionstackv1alpha1.VLLMRuntime{}
		vr.Spec.VLLMConfig.V1 = tc.v1
		vr.Spec.LMCacheConfig.Mode = productionstackv1alpha1.LMCacheModeInProcess
		if got := lmcacheKVTransferConfig(vr); got != tc.want {
			t.Errorf("v1=%v:\n got %s\nwant %s", tc.v1, got, tc.want)
		}
	}
}

// TestLMCacheEmptyModeIsMultiprocess checks a runtime that bypassed API
// defaulting, and so has no mode, gets the default Multiprocess connector.
func TestLMCacheEmptyModeIsMultiprocess(t *testing.T) {
	vr := &productionstackv1alpha1.VLLMRuntime{}
	vr.Spec.VLLMConfig.V1 = true
	got := lmcacheKVTransferConfig(vr)
	if !strings.Contains(got, `"kv_connector":"LMCacheMPConnector"`) {
		t.Errorf("empty mode: kv-transfer-config = %s, want LMCacheMPConnector", got)
	}
}

// TestLMCacheKVTransferConfigMultiprocessIgnoresV1Flag checks Multiprocess mode
// always gets the LMCacheMPConnector, whatever the V1 flag says.
func TestLMCacheKVTransferConfigMultiprocessIgnoresV1Flag(t *testing.T) {
	for _, v1 := range []bool{true, false} {
		vr := &productionstackv1alpha1.VLLMRuntime{}
		vr.Spec.LMCacheConfig.Mode = productionstackv1alpha1.LMCacheModeMultiprocess
		vr.Spec.VLLMConfig.V1 = v1
		got := lmcacheKVTransferConfig(vr)
		if !strings.Contains(got, `"kv_connector":"LMCacheMPConnector"`) {
			t.Errorf("v1=%v: kv-transfer-config = %s, want LMCacheMPConnector", v1, got)
		}
	}
}

func TestLMCacheKVTransferConfigMultiprocess(t *testing.T) {
	vr := &productionstackv1alpha1.VLLMRuntime{}
	vr.Spec.LMCacheConfig.Mode = productionstackv1alpha1.LMCacheModeMultiprocess
	vr.Spec.LMCacheConfig.Multiprocess = productionstackv1alpha1.MPConnectorConfig{
		Host:        "tcp://cacheserver-sample.default.svc.cluster.local",
		Port:        9000,
		IsolatedIPC: true,
	}

	got := lmcacheKVTransferConfig(vr)

	var decoded struct {
		KVConnector string         `json:"kv_connector"`
		KVRole      string         `json:"kv_role"`
		Extra       map[string]any `json:"kv_connector_extra_config"`
	}
	if err := json.Unmarshal([]byte(got), &decoded); err != nil {
		t.Fatalf("rendered config is not valid JSON: %v (%s)", err, got)
	}

	if decoded.KVConnector != "LMCacheMPConnector" {
		t.Errorf("kv_connector = %q", decoded.KVConnector)
	}
	if decoded.Extra["lmcache.mp.host"] != vr.Spec.LMCacheConfig.Multiprocess.Host {
		t.Errorf("host = %v", decoded.Extra["lmcache.mp.host"])
	}
	// The port must stay a JSON number, matching the adapter's expected type.
	if port, ok := decoded.Extra["lmcache.mp.port"].(float64); !ok || port != 9000 {
		t.Errorf("port = %#v, want numeric 9000", decoded.Extra["lmcache.mp.port"])
	}
	// Left empty, the transfer mode still renders as lmcache_driven.
	if decoded.Extra["lmcache.mp.mp_transfer_mode"] != "lmcache_driven" {
		t.Errorf("transfer mode = %v, want lmcache_driven", decoded.Extra["lmcache.mp.mp_transfer_mode"])
	}
	if decoded.Extra["lmcache.mp.isolated_ipc"] != true {
		t.Errorf("isolated_ipc = %v", decoded.Extra["lmcache.mp.isolated_ipc"])
	}
}

func TestLMCacheKVTransferConfigExtraConfigWins(t *testing.T) {
	vr := &productionstackv1alpha1.VLLMRuntime{}
	vr.Spec.LMCacheConfig.Mode = productionstackv1alpha1.LMCacheModeMultiprocess
	vr.Spec.LMCacheConfig.Multiprocess = productionstackv1alpha1.MPConnectorConfig{
		Host: "tcp://a",
		ExtraConfig: map[string]string{
			"lmcache.mp.host":               "tcp://b",
			"lmcache.mp.heartbeat_interval": "5",
		},
	}

	got := lmcacheKVTransferConfig(vr)

	var decoded struct {
		Extra map[string]any `json:"kv_connector_extra_config"`
	}
	if err := json.Unmarshal([]byte(got), &decoded); err != nil {
		t.Fatalf("invalid JSON: %v", err)
	}
	if decoded.Extra["lmcache.mp.host"] != "tcp://b" {
		t.Errorf("extraConfig did not override host: %v", decoded.Extra["lmcache.mp.host"])
	}
	if decoded.Extra["lmcache.mp.heartbeat_interval"] != "5" {
		t.Errorf("extraConfig entry missing: %v", decoded.Extra)
	}
}

func TestKVTransferConfigArg(t *testing.T) {
	args := []string{
		"model", "--port", "8000",
		"--kv-transfer-config", `{"kv_connector":"LMCacheMPConnector"}`,
	}
	if got := kvTransferConfigArg(args); got != `{"kv_connector":"LMCacheMPConnector"}` {
		t.Errorf("value = %q", got)
	}
	if got := kvTransferConfigArg([]string{"model"}); got != "" {
		t.Errorf("absent flag = %q, want empty", got)
	}
	// A trailing flag with no value must not panic.
	if got := kvTransferConfigArg([]string{"--kv-transfer-config"}); got != "" {
		t.Errorf("dangling flag = %q, want empty", got)
	}
}

func TestCacheServerCommandTuningFlags(t *testing.T) {
	cs := mpCacheServer()
	cs.Spec.Multiprocess.L1InitSizeGB = 20
	cs.Spec.Multiprocess.EvictionTriggerWatermark = "0.85"
	cs.Spec.Multiprocess.EvictionRatio = "0.10"
	cs.Spec.Multiprocess.MaxGPUWorkers = 1
	cs.Spec.Multiprocess.MaxCPUWorkers = 8

	got := cacheServerCommand(cs)
	pairs := map[string]string{
		"--l1-init-size-gb":            "20",
		"--eviction-trigger-watermark": "0.85",
		"--eviction-ratio":             "0.10",
		"--max-gpu-workers":            "1",
		"--max-cpu-workers":            "8",
	}
	for flag, want := range pairs {
		if got := argValue(got, flag); got != want {
			t.Errorf("%s = %q, want %q", flag, got, want)
		}
	}

	// Unset tuning fields must stay off the command line so the server keeps
	// its own defaults rather than being pinned to a zero.
	bare := cacheServerCommand(mpCacheServer())
	for flag := range pairs {
		if containsArg(bare, flag) {
			t.Errorf("%s rendered while unset: %v", flag, bare)
		}
	}
}

func TestMaxModelLenArg(t *testing.T) {
	tests := []struct {
		name  string
		value intstr.IntOrString
		want  string
		wantO bool
	}{
		{"unset", intstr.FromInt32(0), "", false},
		{"number", intstr.FromInt32(32768), "32768", true},
		{"auto", intstr.FromString("auto"), "auto", true},
		{"suffixed", intstr.FromString("32k"), "32k", true},
		{"empty string", intstr.FromString(""), "", false},
		// -1 is vLLM's numeric spelling of auto, so it must survive the
		// unset check rather than being treated as absent.
		{"minus one", intstr.FromInt32(-1), "-1", true},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got, ok := maxModelLenArg(tc.value)
			if got != tc.want || ok != tc.wantO {
				t.Errorf("= (%q, %v), want (%q, %v)", got, ok, tc.want, tc.wantO)
			}
		})
	}
}

// argValue returns the token following flag in args, or "".
func argValue(args []string, flag string) string {
	for i, a := range args {
		if a == flag && i+1 < len(args) {
			return args[i+1]
		}
	}
	return ""
}

// TestCacheServerDeploymentStableAfterAPIDefaulting guards against a reconcile
// loop: the API server fills in container port protocols and stores empty
// volume lists as nil, and neither may count as drift.
func TestCacheServerDeploymentStableAfterAPIDefaulting(t *testing.T) {
	r := &CacheServerReconciler{Scheme: newTestScheme()}
	cs := mpCacheServer()
	cs.Name = "cache"
	cs.Namespace = "default"
	cs.Spec.Replicas = 1

	stored := r.deploymentForCacheServer(cs)
	for i := range stored.Spec.Template.Spec.Containers[0].Ports {
		stored.Spec.Template.Spec.Containers[0].Ports[i].Protocol = corev1.ProtocolTCP
	}
	stored.Spec.Template.Spec.Volumes = nil
	stored.Spec.Template.Spec.Containers[0].VolumeMounts = nil

	if r.deploymentNeedsUpdate(stored, cs) {
		t.Fatal("API-server defaulting alone reported as drift; the deployment would be rewritten on every reconcile")
	}

	// A real change must still roll the deployment.
	cs.Spec.Multiprocess.HTTPPort = 8083
	if !r.deploymentNeedsUpdate(stored, cs) {
		t.Error("changed metrics port not detected")
	}
}

// roundTrip passes a Deployment through JSON the way the API server stores and
// returns it: empty lists tagged omitempty come back as nil. Resources are
// copied across unchanged, because a resource.Quantity re-parsed from JSON
// differs from the original in its cached string form only.
func roundTrip(t *testing.T, dep *appsv1.Deployment) *appsv1.Deployment {
	t.Helper()
	raw, err := json.Marshal(dep)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	out := &appsv1.Deployment{}
	if err := json.Unmarshal(raw, out); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	for i := range out.Spec.Template.Spec.Containers {
		out.Spec.Template.Spec.Containers[i].Resources = dep.Spec.Template.Spec.Containers[i].Resources
	}
	return out
}

// TestCacheServerWithoutEnvStableAfterRoundTrip guards against a reconcile
// loop seen on a live cluster: a CacheServer with no env rendered an empty env
// list, the API server returned it as nil, and the two compared unequal, so
// the Deployment was rewritten on every reconcile and status never written.
func TestCacheServerWithoutEnvStableAfterRoundTrip(t *testing.T) {
	r := &CacheServerReconciler{Scheme: newTestScheme()}

	bare := &productionstackv1alpha1.CacheServer{
		Spec: productionstackv1alpha1.CacheServerSpec{
			Port: 9000, Replicas: 1, DeploymentStrategy: "RollingUpdate",
		},
	}
	full := mpCacheServer()
	full.Spec.Replicas = 1
	full.Spec.DeploymentStrategy = "Recreate"

	for name, cs := range map[string]*productionstackv1alpha1.CacheServer{"bare": bare, "full": full} {
		cs.Name, cs.Namespace = "cache", "default"
		if env := cacheServerEnv(cs); env != nil {
			t.Errorf("%s: no env configured, but rendered %#v", name, env)
		}
		stored := roundTrip(t, r.deploymentForCacheServer(cs))
		if r.deploymentNeedsUpdate(stored, cs) {
			t.Errorf("%s: unchanged CacheServer reported as drift after an API round trip", name)
		}
	}
}

// TestCacheServerServicePortsFollowSpec checks the Service is republished when
// its ports no longer match the spec, including a Service left behind by an
// older operator that published the legacy backend on port 80. Without it the
// engines' lmcache.mp.port reaches nothing.
func TestCacheServerServicePortsFollowSpec(t *testing.T) {
	cs := mpCacheServer()
	old := []corev1.ServicePort{{
		Name: "http", Port: 80, TargetPort: intstr.FromInt32(9000), Protocol: corev1.ProtocolTCP,
	}}
	if !servicePortsDiffer(old, cacheServerServicePorts(cs)) {
		t.Error("legacy port-80 Service compared equal to the expected ports")
	}

	moved := mpCacheServer()
	moved.Spec.Port = 9100
	if !servicePortsDiffer(cacheServerServicePorts(cs), cacheServerServicePorts(moved)) {
		t.Error("changed ZMQ port not detected")
	}

	live := cacheServerServicePorts(cs)
	for i := range live {
		live[i].NodePort = 30000 + int32(i) // filled in by the API server, not owned by us
	}
	if servicePortsDiffer(live, cacheServerServicePorts(cs)) {
		t.Error("API-assigned fields reported as Service drift")
	}
}

// mpRuntime builds the smallest VLLMRuntime the controller can render with
// LMCache enabled in Multiprocess mode.
func mpRuntime() *productionstackv1alpha1.VLLMRuntime {
	vr := &productionstackv1alpha1.VLLMRuntime{}
	vr.Name, vr.Namespace = "rt", "default"
	vr.Spec.Model.ModelURL = "Qwen/Qwen3-8B"
	vr.Spec.VLLMConfig.Port = 8000
	vr.Spec.DeploymentConfig.Replicas = 1
	vr.Spec.DeploymentConfig.RuntimeClass = "nvidia"
	vr.Spec.LMCacheConfig.Enabled = true
	vr.Spec.LMCacheConfig.Mode = productionstackv1alpha1.LMCacheModeMultiprocess
	vr.Spec.LMCacheConfig.Multiprocess = productionstackv1alpha1.MPConnectorConfig{
		Host: "tcp://cache.default.svc.cluster.local", Port: 9000,
		TransferMode: "lmcache_driven", IsolatedIPC: true,
	}
	return vr
}

// TestVLLMRuntimeEmptyRuntimeClassIsNil checks runtimeClass "" is left unset.
// A pointer to "" is rejected by the API server ("a lowercase RFC 1123
// subdomain must consist of..."), so the Deployment was never created.
func TestVLLMRuntimeEmptyRuntimeClassIsNil(t *testing.T) {
	r := &VLLMRuntimeReconciler{Scheme: newTestScheme()}
	vr := mpRuntime()
	vr.Spec.DeploymentConfig.RuntimeClass = ""
	if rc := r.deploymentForVLLMRuntime(vr).Spec.Template.Spec.RuntimeClassName; rc != nil {
		t.Errorf("empty runtimeClass rendered as %q, want nil", *rc)
	}

	vr.Spec.DeploymentConfig.RuntimeClass = "nvidia"
	if rc := r.deploymentForVLLMRuntime(vr).Spec.Template.Spec.RuntimeClassName; rc == nil || *rc != "nvidia" {
		t.Errorf("runtimeClass nvidia rendered as %v", rc)
	}
}

// TestVLLMRuntimeMultiprocessStable checks an unchanged multiprocess runtime
// without nodeSelectorTerms is not reported as drift. Such a runtime renders
// no affinity at all, which the comparison must handle rather than dereference.
func TestVLLMRuntimeMultiprocessStable(t *testing.T) {
	r := &VLLMRuntimeReconciler{Scheme: newTestScheme()}
	vr := mpRuntime()
	stored := roundTrip(t, r.deploymentForVLLMRuntime(vr))
	if stored.Spec.Template.Spec.Affinity != nil {
		t.Fatalf("runtime without nodeSelectorTerms rendered affinity %#v", stored.Spec.Template.Spec.Affinity)
	}
	if r.deploymentNeedsUpdate(context.Background(), stored, vr) {
		t.Error("unchanged multiprocess runtime reported as drift")
	}
}

// TestVLLMRuntimeMultiprocessDrift checks the multiprocess settings that are
// rendered outside the compared env vars still roll the pods when changed.
func TestVLLMRuntimeMultiprocessDrift(t *testing.T) {
	r := &VLLMRuntimeReconciler{Scheme: newTestScheme()}
	stored := r.deploymentForVLLMRuntime(mpRuntime())

	for name, mutate := range map[string]func(*productionstackv1alpha1.VLLMRuntime){
		"hostIPC": func(vr *productionstackv1alpha1.VLLMRuntime) { vr.Spec.DeploymentConfig.HostIPC = true },
		"host":    func(vr *productionstackv1alpha1.VLLMRuntime) { vr.Spec.LMCacheConfig.Multiprocess.Host = "tcp://other" },
		"isolatedIpc": func(vr *productionstackv1alpha1.VLLMRuntime) {
			vr.Spec.LMCacheConfig.Multiprocess.IsolatedIPC = false
		},
		"port": func(vr *productionstackv1alpha1.VLLMRuntime) { vr.Spec.LMCacheConfig.Multiprocess.Port = 9100 },
		// Disabling LMCache is detected through the kv-transfer-config arg,
		// which disappears; no LMCache env var is compared any more.
		"disabled": func(vr *productionstackv1alpha1.VLLMRuntime) { vr.Spec.LMCacheConfig.Enabled = false },
		"mode": func(vr *productionstackv1alpha1.VLLMRuntime) {
			vr.Spec.LMCacheConfig.Mode = productionstackv1alpha1.LMCacheModeInProcess
		},
	} {
		vr := mpRuntime()
		mutate(vr)
		if !r.deploymentNeedsUpdate(context.Background(), stored, vr) {
			t.Errorf("%s change not detected as drift", name)
		}
	}
}

// TestVLLMRuntimeMultiprocessSkipsInProcessEnv checks none of the in-process
// LMCache variables are rendered in Multiprocess mode, even with the API
// defaults of the in-process fields set: the engine holds no cache of its own,
// and these would start one inside the engine process.
func TestVLLMRuntimeMultiprocessSkipsInProcessEnv(t *testing.T) {
	r := &VLLMRuntimeReconciler{Scheme: newTestScheme()}
	vr := mpRuntime()
	vr.Spec.VLLMConfig.V1 = true
	vr.Spec.LMCacheConfig.CPUOffloadingBufferSize = "4Gi"
	vr.Spec.LMCacheConfig.DiskOffloadingBufferSize = "8Gi"
	vr.Spec.LMCacheConfig.RemoteURL = "redis://cache:6379"

	c := r.deploymentForVLLMRuntime(vr).Spec.Template.Spec.Containers[0]
	for _, e := range c.Env {
		switch e.Name {
		case "LMCACHE_USE_EXPERIMENTAL", "LMCACHE_LOCAL_CPU", "LMCACHE_MAX_LOCAL_CPU_SIZE",
			"LMCACHE_LOCAL_DISK", "LMCACHE_MAX_LOCAL_DISK_SIZE",
			"LMCACHE_REMOTE_URL", "LMCACHE_REMOTE_SERDE":
			t.Errorf("in-process variable %s rendered", e.Name)
		}
	}
	if cfg := argValue(c.Args, "--kv-transfer-config"); !strings.Contains(cfg, `"kv_connector":"LMCacheMPConnector"`) {
		t.Errorf("kv-transfer-config = %s, want LMCacheMPConnector", cfg)
	}
}

// TestVLLMRuntimeEnablingLMCacheIsDrift checks a runtime deployed without
// LMCache rolls when LMCache is turned on.
func TestVLLMRuntimeEnablingLMCacheIsDrift(t *testing.T) {
	r := &VLLMRuntimeReconciler{Scheme: newTestScheme()}
	off := mpRuntime()
	off.Spec.LMCacheConfig.Enabled = false
	stored := roundTrip(t, r.deploymentForVLLMRuntime(off))

	if r.deploymentNeedsUpdate(context.Background(), stored, off) {
		t.Error("unchanged runtime without LMCache reported as drift")
	}
	if !r.deploymentNeedsUpdate(context.Background(), stored, mpRuntime()) {
		t.Error("enabling LMCache not detected as drift")
	}
}

// ipRuntime builds the smallest VLLMRuntime the controller can render with
// LMCache enabled in InProcess mode, with the API defaults filled in.
func ipRuntime() *productionstackv1alpha1.VLLMRuntime {
	vr := &productionstackv1alpha1.VLLMRuntime{}
	vr.Name, vr.Namespace = "rt", "default"
	vr.Spec.Model.ModelURL = "Qwen/Qwen3-8B"
	vr.Spec.VLLMConfig.Port = 8000
	vr.Spec.VLLMConfig.V1 = true
	vr.Spec.DeploymentConfig.Replicas = 1
	vr.Spec.LMCacheConfig.Enabled = true
	vr.Spec.LMCacheConfig.Mode = productionstackv1alpha1.LMCacheModeInProcess
	vr.Spec.LMCacheConfig.CPUOffloadingBufferSize = "20"
	vr.Spec.LMCacheConfig.DiskOffloadingBufferSize = "8Gi"
	return vr
}

// TestVLLMRuntimeInProcessEnvMatchesMain checks InProcess mode renders the
// LMCache env main always has, in the same order.
func TestVLLMRuntimeInProcessEnvMatchesMain(t *testing.T) {
	r := &VLLMRuntimeReconciler{Scheme: newTestScheme()}
	vr := ipRuntime()
	vr.Spec.LMCacheConfig.RemoteURL = "redis://cache:6379"
	vr.Spec.LMCacheConfig.RemoteSerde = "naive"

	var got []string
	for _, e := range r.deploymentForVLLMRuntime(vr).Spec.Template.Spec.Containers[0].Env {
		if strings.HasPrefix(e.Name, "LMCACHE_") || e.Name == "VLLM_RPC_TIMEOUT" {
			got = append(got, e.Name+"="+e.Value)
		}
	}
	want := []string{
		"LMCACHE_LOG_LEVEL=DEBUG",
		"LMCACHE_USE_EXPERIMENTAL=True",
		"VLLM_RPC_TIMEOUT=1000000",
		"LMCACHE_LOCAL_CPU=True",
		"LMCACHE_MAX_LOCAL_CPU_SIZE=20",
		"LMCACHE_LOCAL_DISK=True",
		"LMCACHE_MAX_LOCAL_DISK_SIZE=8Gi",
		"LMCACHE_REMOTE_URL=redis://cache:6379",
		"LMCACHE_REMOTE_SERDE=naive",
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("in-process env:\n got %v\nwant %v", got, want)
	}
}

// TestVLLMRuntimeInProcessStable checks an unchanged InProcess runtime is not
// reported as drift after an API round trip.
func TestVLLMRuntimeInProcessStable(t *testing.T) {
	r := &VLLMRuntimeReconciler{Scheme: newTestScheme()}
	stored := roundTrip(t, r.deploymentForVLLMRuntime(ipRuntime()))
	if r.deploymentNeedsUpdate(context.Background(), stored, ipRuntime()) {
		t.Error("unchanged in-process runtime reported as drift")
	}
}

// TestVLLMRuntimeInProcessDrift checks a changed in-process setting, which is
// rendered as an env var rather than an arg, still rolls the engine, and that
// switching modes does too.
func TestVLLMRuntimeInProcessDrift(t *testing.T) {
	r := &VLLMRuntimeReconciler{Scheme: newTestScheme()}
	stored := roundTrip(t, r.deploymentForVLLMRuntime(ipRuntime()))

	for name, mutate := range map[string]func(*productionstackv1alpha1.VLLMRuntime){
		"cpu size":     func(vr *productionstackv1alpha1.VLLMRuntime) { vr.Spec.LMCacheConfig.CPUOffloadingBufferSize = "30" },
		"disk removed": func(vr *productionstackv1alpha1.VLLMRuntime) { vr.Spec.LMCacheConfig.DiskOffloadingBufferSize = "" },
		"remote added": func(vr *productionstackv1alpha1.VLLMRuntime) { vr.Spec.LMCacheConfig.RemoteURL = "redis://cache:6379" },
		"v1 flag":      func(vr *productionstackv1alpha1.VLLMRuntime) { vr.Spec.VLLMConfig.V1 = false },
		"to multiprocess": func(vr *productionstackv1alpha1.VLLMRuntime) {
			vr.Spec.LMCacheConfig.Mode = productionstackv1alpha1.LMCacheModeMultiprocess
		},
	} {
		vr := ipRuntime()
		mutate(vr)
		if !r.deploymentNeedsUpdate(context.Background(), stored, vr) {
			t.Errorf("%s change not detected as drift", name)
		}
	}
}

// TestVLLMRuntimeMultiprocessStableWithInProcessDefaults guards against a
// reconcile loop: the API fills in the in-process buffer sizes even on a
// Multiprocess runtime, where they are not rendered, so comparing them would
// report drift that no update can resolve.
func TestVLLMRuntimeMultiprocessStableWithInProcessDefaults(t *testing.T) {
	r := &VLLMRuntimeReconciler{Scheme: newTestScheme()}
	vr := mpRuntime()
	vr.Spec.LMCacheConfig.CPUOffloadingBufferSize = "4Gi"
	vr.Spec.LMCacheConfig.DiskOffloadingBufferSize = "8Gi"
	stored := roundTrip(t, r.deploymentForVLLMRuntime(vr))
	if r.deploymentNeedsUpdate(context.Background(), stored, vr) {
		t.Error("multiprocess runtime with in-process API defaults reported as drift")
	}
}
