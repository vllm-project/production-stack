/*
Copyright 2025 The vLLM Production Stack Authors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0
*/

package picker

import (
	"math/rand"
	"sync"
	"time"

	"sigs.k8s.io/gateway-api-inference-extension/pkg/epp/scheduling/plugins"
	"sigs.k8s.io/gateway-api-inference-extension/pkg/epp/scheduling/types"
)

var _ plugins.Picker = &PrefixMatchPicker{}

// PrefixMatchPicker selects the engine whose URL was returned by the
// longest-prefix match against previously-seen prompts (same idea as the
// Python `route_request`). Ties are broken at random.
type PrefixMatchPicker struct {
	trie *hashTrie
	rnd  *rand.Rand
}

// NewPrefixMatchPicker returns a ready-to-use picker instance.
func NewPrefixMatchPicker() *PrefixMatchPicker {
	return &PrefixMatchPicker{
		trie: newHashTrie(),
		rnd:  rand.New(rand.NewSource(time.Now().UnixNano())),
	}
}

func (p *PrefixMatchPicker) Name() string { return "prefixmatch" }

// Pick implements plugins.Picker.
//
// SchedulingContext is assumed to carry the inference request body in
// ctx.RequestBody (map[string]any) with the prompt at key "prompt".  Adjust
// the accessor if your integration differs.
func (p *PrefixMatchPicker) Pick(
	ctx *types.SchedulingContext,
	scoredPods []*types.ScoredPod,
) *types.Result {
	if len(scoredPods) == 0 {
		return &types.Result{}
	}

	prompt, _ := ctx.RequestBody["prompt"].(string)

	// 1. Build the set of available endpoints.
	available := make(map[string]struct{}, len(scoredPods))
	for _, sp := range scoredPods {
		ep := sp.GetPod().EndpointURL // <-- adapt this accessor
		available[ep] = struct{}{}
	}

	// 2. Longest-prefix match within the trie.
	matched := p.trie.longestPrefixMatch(prompt, available)

	// 3. Fallback: no match --> all endpoints are candidates.
	if len(matched) == 0 {
		for ep := range available {
			matched[ep] = struct{}{}
		}
	}

	// 4. Convert the matched set to a slice and pick randomly.
	endpoints := make([]string, 0, len(matched))
	for ep := range matched {
		endpoints = append(endpoints, ep)
	}
	selected := endpoints[p.rnd.Intn(len(endpoints))]

	// 5. Cache the decision for future prefix look-ups.
	p.trie.insert(prompt, selected)

	// 6. Return the pod whose URL matches `selected`.
	for _, sp := range scoredPods {
		if sp.GetPod().EndpointURL == selected { // same accessor as above
			return &types.Result{TargetPod: sp}
		}
	}
	// Should never hit; safe fallback.
	return &types.Result{TargetPod: scoredPods[0]}
}

/*---------------------------- trie implementation ---------------------------*/

type hashTrie struct {
	mu        sync.RWMutex
	children  map[rune]*hashTrie
	endpoints map[string]struct{}
}

func newHashTrie() *hashTrie {
	return &hashTrie{children: make(map[rune]*hashTrie)}
}

func (t *hashTrie) insert(key, endpoint string) {
	t.mu.Lock()
	defer t.mu.Unlock()

	node := t
	for _, r := range key {
		child, ok := node.children[r]
		if !ok {
			child = newHashTrie()
			node.children[r] = child
		}
		node = child
	}
	if node.endpoints == nil {
		node.endpoints = make(map[string]struct{})
	}
	node.endpoints[endpoint] = struct{}{}
}

func (t *hashTrie) longestPrefixMatch(
	key string,
	available map[string]struct{},
) map[string]struct{} {
	t.mu.RLock()
	defer t.mu.RUnlock()

	var lastMatch map[string]struct{}
	node := t
	for _, r := range key {
		if node.endpoints != nil {
			lastMatch = node.endpoints
		}
		child, ok := node.children[r]
		if !ok {
			break
		}
		node = child
	}
	// Filter by `available`.
	res := make(map[string]struct{})
	for ep := range lastMatch {
		if _, ok := available[ep]; ok {
			res[ep] = struct{}{}
		}
	}
	return res
}