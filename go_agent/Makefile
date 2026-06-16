VERSION ?= 0.2.0
LDFLAGS := -s -w -X github.com/complete3tech/scc-agent/internal/version.Version=$(VERSION)
PKG := ./cmd/scc-agent
CMD_DIR := cmd/scc-agent
GOVERSIONINFO := github.com/josephspurrier/goversioninfo/cmd/goversioninfo@latest

.PHONY: build windows test tidy lint clean

build:
	go build -ldflags "$(LDFLAGS)" -o dist/scc-agent $(PKG)

# Two Windows binaries built from the same code (the proven, working layout):
#   scc-agent.exe       — the service/agent. Console subsystem, NO manifest, so
#                         the Service Control Manager can start it as LocalSystem.
#   scc-agent-setup.exe — installer + settings GUI. GUI subsystem + UAC manifest
#                         (requireAdministrator) so a double-click elevates and
#                         shows no console; it registers scc-agent.exe as the service.
# A combined GUI + requireAdministrator exe cannot be launched by the SCM, which
# is why the single-exe build failed to start as a service.
windows:
	# 1) service binary — ensure no manifest .syso is linked in
	rm -f $(CMD_DIR)/resource_windows_amd64.syso
	GOOS=windows GOARCH=amd64 go build -ldflags "$(LDFLAGS)" -o dist/scc-agent.exe $(PKG)
	# 2) setup/GUI binary — embed UAC manifest (+icon if present), GUI subsystem
	go run $(GOVERSIONINFO) -64 \
		-manifest $(CMD_DIR)/manifest.xml \
		-o $(CMD_DIR)/resource_windows_amd64.syso \
		$(if $(wildcard $(CMD_DIR)/icon.ico),-icon $(CMD_DIR)/icon.ico,) \
		$(CMD_DIR)/versioninfo.json
	GOOS=windows GOARCH=amd64 go build -ldflags "$(LDFLAGS) -H windowsgui" -o dist/scc-agent-setup.exe $(PKG)
	# 3) drop the generated syso so it can't leak into a later plain build
	rm -f $(CMD_DIR)/resource_windows_amd64.syso

test:
	go test ./...

tidy:
	go mod tidy

lint:
	go vet ./...

clean:
	rm -rf dist $(CMD_DIR)/resource_windows_amd64.syso
