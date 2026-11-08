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

package v1alpha1

import (
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// EDIT THIS FILE!  THIS IS SCAFFOLDING FOR YOU TO OWN!
// NOTE: json tags are required.  Any new fields you add must have json tags for the fields to be serialized.

// CacheServerSpec defines the desired state of CacheServer
type CacheServerSpec struct {
	// Image configuration for the cache server
	Image ImageSpec `json:"image"`

	// Port is the ZMQ port the cache server listens on and the Service
	// exposes. Engines reach it through lmCacheConfig.multiprocess.port.
	// +kubebuilder:default=9000
	Port int32 `json:"port"`

	// Resource requirements
	Resources ResourceRequirements `json:"resources"`

	// Number of replicas
	// +kubebuilder:default=1
	Replicas int32 `json:"replicas"`

	// Deployment strategy
	// +kubebuilder:validation:Enum=RollingUpdate;Recreate
	// +kubebuilder:default=RollingUpdate
	DeploymentStrategy string `json:"deploymentStrategy"`

	// Multiprocess configures the `lmcache server` process. The block may be
	// left out, in which case every flag takes its default.
	// +kubebuilder:default={}
	Multiprocess MultiprocessSpec `json:"multiprocess,omitempty"`

	// Env holds extra environment variables for the cache server container.
	Env []EnvVar `json:"env,omitempty"`

	// HostIPC places the cache server in the host IPC namespace, shared with
	// engine pods on the same node that also set hostIPC. It is the
	// alternative to multiprocess.isolatedIpc; with isolatedIpc it is not
	// needed.
	HostIPC bool `json:"hostIPC,omitempty"`

	// Volumes are extra volumes for the cache server pod, typically the backing
	// store for an L2 adapter. Without one, an L2 tier writes to the
	// container's ephemeral filesystem and is lost on restart.
	Volumes []corev1.Volume `json:"volumes,omitempty"`

	// VolumeMounts are extra mounts for the cache server container. Mount paths
	// must line up with the base_path of the matching L2 adapter.
	VolumeMounts []corev1.VolumeMount `json:"volumeMounts,omitempty"`

	// RuntimeClassName selects the container runtime for the cache server pod.
	// In lmcache_driven mode the pod must see the engines' GPUs without
	// requesting one, which on some clusters only works under a specific
	// RuntimeClass (commonly "nvidia"). Empty leaves the node default.
	RuntimeClassName string `json:"runtimeClassName,omitempty"`
}

// MultiprocessSpec configures the `lmcache server` multiprocess cache server.
// Each field maps to one command line flag; empty fields are left off the
// command line so the server applies its own default.
type MultiprocessSpec struct {
	// TransferMode maps to --supported-transfer-mode and must agree with the
	// engine's lmcache.mp.mp_transfer_mode.
	//
	// lmcache_driven, the only supported mode, has the server copy KV out of
	// the engines' GPU memory over CUDA IPC. The cache server must therefore
	// run on the engines' node and see their GPUs.
	// +kubebuilder:validation:Enum=lmcache_driven
	// +kubebuilder:default=lmcache_driven
	TransferMode string `json:"transferMode,omitempty"`

	// L1SizeGB maps to --l1-size-gb, the host DRAM hot tier in GB. Required
	// by the server, so the operator always renders it.
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:default=10
	L1SizeGB int32 `json:"l1SizeGb,omitempty"`

	// EvictionPolicy maps to --eviction-policy. Required by the server, so the
	// operator always renders it.
	// +kubebuilder:validation:Enum=LRU;IsolatedLRU;noop
	// +kubebuilder:default=LRU
	EvictionPolicy string `json:"evictionPolicy,omitempty"`

	// ChunkSize maps to --chunk-size and must match the engine's chunk size.
	// For hybrid (Mamba/GDN) models it must also be a multiple of the unified
	// vLLM block size, otherwise registration fails.
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:default=256
	ChunkSize int32 `json:"chunkSize,omitempty"`

	// HTTPPort maps to --http-port, the metrics and control HTTP frontend.
	// +kubebuilder:default=8080
	HTTPPort int32 `json:"httpPort,omitempty"`

	// L1InitSizeGB maps to --l1-init-size-gb, how much of the L1 arena is
	// allocated up front under lazy allocation. The rest is faulted in on
	// demand, so a small value shortens startup on a large L1.
	// +kubebuilder:validation:Minimum=0
	L1InitSizeGB int32 `json:"l1InitSizeGb,omitempty"`

	// L1AlignBytes maps to --l1-align-bytes. Set it to the O_DIRECT alignment
	// of the L2 filesystem (typically 4096) when an adapter enables use_odirect.
	L1AlignBytes int32 `json:"l1AlignBytes,omitempty"`

	// EvictionTriggerWatermark maps to --eviction-trigger-watermark, the L1
	// occupancy fraction (0.0 to 1.0) at which eviction starts.
	// +kubebuilder:validation:Pattern=`^(0(\.[0-9]+)?|1(\.0+)?)$`
	EvictionTriggerWatermark string `json:"evictionTriggerWatermark,omitempty"`

	// EvictionRatio maps to --eviction-ratio, the fraction of L1 (0.0 to 1.0)
	// freed each time eviction runs.
	// +kubebuilder:validation:Pattern=`^(0(\.[0-9]+)?|1(\.0+)?)$`
	EvictionRatio string `json:"evictionRatio,omitempty"`

	// L2Adapters maps to repeated --l2-adapter flags. Each entry is a JSON
	// object describing one cold tier, for example
	// {"type":"fs_native","base_path":"/mnt/kvcache","use_odirect":true}.
	L2Adapters []string `json:"l2Adapters,omitempty"`

	// SeparateObjectGroups maps to --separate-object-groups, splitting kernel
	// groups into one object group per sliding-window size at registration.
	// Needed for hybrid models whose KV cache spans several groups.
	SeparateObjectGroups bool `json:"separateObjectGroups,omitempty"`

	// IsolatedIPC maps to --isolated-ipc, for engine workers and the server that
	// share no host IPC namespace or /dev/shm. Must match the engine's
	// lmcache.mp.isolated_ipc.
	IsolatedIPC bool `json:"isolatedIpc,omitempty"`

	// MaxWorkers maps to --max-workers, the base worker thread count for both
	// the GPU and CPU pools. MaxGPUWorkers and MaxCPUWorkers override it
	// per pool.
	MaxWorkers int32 `json:"maxWorkers,omitempty"`

	// MaxGPUWorkers maps to --max-gpu-workers, the threads serving STORE and
	// RETRIEVE. Defaults to MaxWorkers.
	MaxGPUWorkers int32 `json:"maxGpuWorkers,omitempty"`

	// MaxCPUWorkers maps to --max-cpu-workers, the threads serving LOOKUP and
	// other non-transfer requests. Defaults to MaxWorkers.
	MaxCPUWorkers int32 `json:"maxCpuWorkers,omitempty"`

	// InstanceID maps to --instance-id, the stable identity reported to the
	// coordinator and to OpenTelemetry. Defaults to a random UUID per start.
	InstanceID string `json:"instanceId,omitempty"`

	// ExtraArgs are appended verbatim to the server command line, for flags the
	// spec does not model.
	ExtraArgs []string `json:"extraArgs,omitempty"`
}

// CacheServerStatus defines the observed state of CacheServer
type CacheServerStatus struct {
	// Last time the status was updated
	LastUpdated metav1.Time `json:"lastUpdated,omitempty"`

	// Current status of the cache server
	Status string `json:"status,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:printcolumn:name="Status",type="string",JSONPath=".status.status"
// +kubebuilder:printcolumn:name="Age",type="date",JSONPath=".metadata.creationTimestamp"

// CacheServer is the Schema for the cacheservers API
type CacheServer struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   CacheServerSpec   `json:"spec,omitempty"`
	Status CacheServerStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// CacheServerList contains a list of CacheServer
type CacheServerList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []CacheServer `json:"items"`
}

func init() {
	SchemeBuilder.Register(&CacheServer{}, &CacheServerList{})
}
