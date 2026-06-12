// Package version holds the agent's build version, mirrored from the Python
// agent's __init__.py / pyproject.toml. Override at build time with
// -ldflags "-X github.com/complete3tech/scc-agent/internal/version.Version=x.y.z".
package version

var Version = "0.2.0"
