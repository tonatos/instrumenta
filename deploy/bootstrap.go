package main

import (
	"fmt"

	"github.com/booyaka101/porter"
)

func buildBootstrapTasks(inv Inventory, envContent string, hysteriaContent string, hysteriaEnabled bool) []porter.Task {
	builders := []porter.TaskBuilder{
		porter.EnsurePackage("ca-certificates").Name("Install ca-certificates"),
		porter.EnsurePackage("curl").Name("Install curl"),
		porter.EnsurePackage("git").Name("Install git"),

		porter.Run(
			"command -v docker >/dev/null 2>&1 || curl -fsSL https://get.docker.com | sh",
		).Name("Install Docker").Sudo(),

		porter.Run(
			"docker compose version >/dev/null 2>&1 || apt-get update && apt-get install -y docker-compose-plugin",
		).Name("Install Docker Compose plugin").Sudo(),

		porter.Run(gitBootstrapCommand(inv)).Name("Clone or update application from GitHub").Sudo(),

		porter.Run(fmt.Sprintf("mkdir -p %s/cache", shellQuote(inv.AppDir))).
			Name("Ensure application cache directory").Sudo(),

		porter.Run(tlsDirectoriesCommand(inv)).Name("Ensure shared TLS directories exist").Sudo(),

		porter.EnsureFile(inv.AppDir+"/.env", envContent).
			Mode("0600").
			Name("Generate production .env").
			Sudo(),
	}

	hysteriaPath := inv.AppDir + "/hysteria-client.yaml"
	if hysteriaEnabled {
		builders = append(builders,
			porter.EnsureFile(hysteriaPath, hysteriaContent).
				Mode("0600").
				Name("Generate Hysteria2 client config").
				Sudo(),
		)
	} else {
		builders = append(builders,
			porter.Run(fmt.Sprintf("rm -f %s", shellQuote(hysteriaPath))).
				Name("Remove Hysteria2 client config (disabled)").
				Sudo(),
		)
	}

	if inv.GHCRToken != "" {
		builders = append(builders,
			porter.Run(fmt.Sprintf(
				"echo %s | docker login ghcr.io -u %s --password-stdin",
				shellQuote(inv.GHCRToken),
				shellQuote(inv.GHCRUsername),
			)).Name("Log in to GitHub Container Registry").Sudo(),
		)
	}

	builders = append(builders,
		porter.Run(composeDeployCommand(inv)).Name("Deploy Instrumenta stack").Sudo(),
	)

	return porter.Tasks(builders...)
}

func gitBootstrapCommand(inv Inventory) string {
	appDir := shellQuote(inv.AppDir)
	repo := shellQuote(inv.GitRepo)
	branch := shellQuote(inv.GitBranch)
	return fmt.Sprintf(
		`if [ ! -d %s/.git ]; then GIT_SSH_COMMAND='ssh -o StrictHostKeyChecking=accept-new' git clone --branch %s %s %s; else git -C %s fetch origin %s && git -C %s reset --hard origin/%s; fi`,
		appDir, branch, repo, appDir, appDir, branch, appDir, branch,
	)
}

func tlsDirectoriesCommand(inv Inventory) string {
	dataDir := shellQuote(inv.TLSCaddyDataDir)
	configDir := shellQuote(inv.TLSCaddyConfigDir)
	return fmt.Sprintf(
		`mkdir -p %s %s && chmod 755 %s %s`,
		dataDir, configDir, dataDir, configDir,
	)
}

func composeDeployCommand(inv Inventory) string {
	return fmt.Sprintf(
		"cd %s && IMAGE_TAG=%s docker compose -p %s %s pull && IMAGE_TAG=%s docker compose -p %s %s up -d --remove-orphans",
		shellQuote(inv.AppDir),
		shellQuote(inv.ImageTag),
		shellQuote(inv.ProjectName),
		inv.composeFilesFlag(),
		shellQuote(inv.ImageTag),
		shellQuote(inv.ProjectName),
		inv.composeFilesFlag(),
	)
}
