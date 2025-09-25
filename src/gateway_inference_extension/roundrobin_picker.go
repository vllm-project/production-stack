/*
Copyright 2025 The vLLM Production Stack Authors.

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

package picker

import (
	"fmt"
	"sort"
	"sync/atomic"

	"sigs.k8s.io/gateway-api-inference-extension/pkg/epp/scheduling/plugins"
	"sigs.k8s.io/gateway-api-inference-extension/pkg/epp/scheduling/types"
	logutil "sigs.k8s.io/gateway-api-inference-extension/pkg/epp/util/logging"
)

var _ plugins.Picker = &RoundRobinPicker{}

// RoundRobinPicker picks pods in a round-robin fashion, cycling through the list of candidates.
type RoundRobinPicker struct {
	// currentIndex tracks the current position in the list of pods
	currentIndex uint64
}

func (p *RoundRobinPicker) Name() string {
	return "roundrobin"
}

func (p *RoundRobinPicker) Pick(ctx *types.SchedulingContext, scoredPods []*types.ScoredPod) *types.Result {
	if len(scoredPods) == 0 {
		return &types.Result{}
	}
	// sort the candidates by NamespacedName
	sort.Slice(scoredPods, func(i, j int) bool {
		return scoredPods[i].GetPod().NamespacedName.String() < scoredPods[j].GetPod().NamespacedName.String()
	})
	ctx.Logger.V(logutil.DEBUG).Info(fmt.Sprintf("Sorted candidates: %+v", scoredPods))
	// select the next pod in the list
	index := int(atomic.AddUint64(&p.currentIndex, 1) - 1)
	index = index % len(scoredPods)
	ctx.Logger.V(logutil.DEBUG).Info(fmt.Sprintf("Selecting pod at index %d from %d candidates in a round-robin fashion: %+v",
		index, len(scoredPods), scoredPods))

	return &types.Result{TargetPod: scoredPods[index]}

}
