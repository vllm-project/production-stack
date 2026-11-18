/*
Copyright 2026.

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
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"strings"
	"testing"

	apiextensionsv1 "k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1"
	"k8s.io/apimachinery/pkg/util/yaml"
)

type resourceSchemaLocation struct {
	crdName string
	path    []string
}

var resourceSchemaLocations = []resourceSchemaLocation{
	{crdName: "production-stack.vllm.ai_cacheservers.yaml", path: []string{"spec", "resources"}},
	{crdName: "production-stack.vllm.ai_vllmrouters.yaml", path: []string{"spec", "resources"}},
	{crdName: "production-stack.vllm.ai_vllmruntimes.yaml", path: []string{"spec", "deploymentConfig", "resources"}},
	{crdName: "production-stack.vllm.ai_vllmruntimes.yaml", path: []string{"spec", "deploymentConfig", "sidecarConfig", "resources"}},
}

func TestGeneratedCRDsValidateFlatResourceQuantities(t *testing.T) {
	for _, location := range resourceSchemaLocations {
		location := location
		t.Run(fmt.Sprintf("%s/%v", location.crdName, location.path), func(t *testing.T) {
			crd := readSingleCRD(t, filepath.Join("..", "..", "config", "crd", "bases", location.crdName))
			resources := schemaAtPath(t, crd, location.path)

			for _, field := range []string{"cpu", "memory", "gpu"} {
				fieldSchema, ok := resources.Properties[field]
				if !ok {
					t.Fatalf("resource schema does not define %q", field)
				}
				if fieldSchema.Pattern == "" {
					t.Fatalf("flat resource field %q has no quantity validation pattern", field)
				}
				pattern, err := regexp.Compile(fieldSchema.Pattern)
				if err != nil {
					t.Fatalf("compile %s pattern %q: %v", field, fieldSchema.Pattern, err)
				}
				for _, invalid := range []string{"not-a-quantity", "1.2.3", "--1"} {
					if pattern.MatchString(invalid) {
						t.Errorf("%s pattern unexpectedly accepts %q", field, invalid)
					}
				}
				for _, valid := range []string{"", "500m", "2", "4Gi", "1e3"} {
					if !pattern.MatchString(valid) {
						t.Errorf("%s pattern unexpectedly rejects %q", field, valid)
					}
				}
			}
		})
	}
}

func TestGeneratedCRDsValidateExtendedGPUResources(t *testing.T) {
	for _, location := range resourceSchemaLocations {
		location := location
		t.Run(fmt.Sprintf("%s/%v", location.crdName, location.path), func(t *testing.T) {
			crd := readSingleCRD(t, filepath.Join("..", "..", "config", "crd", "bases", location.crdName))
			resources := schemaAtPath(t, crd, location.path)

			gpu := resources.Properties["gpu"]
			if !hasValidationRule(gpu, "quantity(self).isInteger()") ||
				!hasValidationRule(gpu, "sign(quantity(self)) >= 0") {
				t.Fatalf("GPU schema does not require a nonnegative integral quantity: %#v", gpu.XValidations)
			}

			gpuType := resources.Properties["gpuType"]
			if gpuType.Pattern == "" {
				t.Fatal("gpuType schema does not require a qualified resource name")
			}
			if !hasValidationRule(gpuType, "!self.startsWith('requests.')") ||
				!hasValidationRule(gpuType, "!self.contains('kubernetes.io/')") {
				t.Fatalf("gpuType schema does not reject native or quota resource names: %#v", gpuType.XValidations)
			}
		})
	}
}

func TestDocumentedInstallerContainsGeneratedResourceSchemas(t *testing.T) {
	installer := readCRDs(t, filepath.Join("..", "..", "config", "default.yaml"))

	for _, location := range resourceSchemaLocations {
		location := location
		t.Run(fmt.Sprintf("%s/%v", location.crdName, location.path), func(t *testing.T) {
			generated := readSingleCRD(t, filepath.Join("..", "..", "config", "crd", "bases", location.crdName))
			installed, ok := installer[generated.Name]
			if !ok {
				t.Fatalf("documented installer does not contain CRD %q", generated.Name)
			}

			generatedResources := schemaAtPath(t, generated, location.path)
			installedResources := schemaAtPath(t, installed, location.path)
			if !reflect.DeepEqual(generatedResources, installedResources) {
				t.Fatalf("documented installer resource schema for %s at %v differs from generated CRD", generated.Name, location.path)
			}
		})
	}
}

func readSingleCRD(t *testing.T, path string) apiextensionsv1.CustomResourceDefinition {
	t.Helper()
	crds := readCRDs(t, path)
	if len(crds) != 1 {
		t.Fatalf("expected one CRD in %s, got %d", path, len(crds))
	}
	for _, crd := range crds {
		return crd
	}
	panic("unreachable")
}

func readCRDs(t *testing.T, path string) map[string]apiextensionsv1.CustomResourceDefinition {
	t.Helper()
	file, err := os.Open(path)
	if err != nil {
		t.Fatalf("open %s: %v", path, err)
	}
	defer file.Close()

	crds := map[string]apiextensionsv1.CustomResourceDefinition{}
	decoder := yaml.NewYAMLOrJSONDecoder(file, 4096)
	for {
		var crd apiextensionsv1.CustomResourceDefinition
		if err := decoder.Decode(&crd); err != nil {
			if err == io.EOF {
				break
			}
			t.Fatalf("decode %s: %v", path, err)
		}
		if crd.Kind == "CustomResourceDefinition" {
			crds[crd.Name] = crd
		}
	}
	return crds
}

func schemaAtPath(
	t *testing.T,
	crd apiextensionsv1.CustomResourceDefinition,
	path []string,
) apiextensionsv1.JSONSchemaProps {
	t.Helper()
	if len(crd.Spec.Versions) != 1 || crd.Spec.Versions[0].Schema == nil ||
		crd.Spec.Versions[0].Schema.OpenAPIV3Schema == nil {
		t.Fatalf("CRD %s does not have exactly one version with an OpenAPI schema", crd.Name)
	}

	schema := *crd.Spec.Versions[0].Schema.OpenAPIV3Schema
	for _, component := range path {
		next, ok := schema.Properties[component]
		if !ok {
			t.Fatalf("CRD %s schema path %v is missing %q", crd.Name, path, component)
		}
		schema = next
	}
	return schema
}

func hasValidationRule(schema apiextensionsv1.JSONSchemaProps, fragment string) bool {
	for _, validation := range schema.XValidations {
		if strings.Contains(validation.Rule, fragment) {
			return true
		}
	}
	return false
}
