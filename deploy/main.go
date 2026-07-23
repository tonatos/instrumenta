package main

import (
	"fmt"
	"log"
	"os"
	"strings"

	"github.com/booyaka101/porter"
)

func main() {
	command, inventoryPath, sshKey, dryRun, err := parseCLI(os.Args[1:])
	if err != nil {
		fmt.Fprintf(os.Stderr, "%v\n", err)
		os.Exit(2)
	}

	inv, err := LoadInventory(inventoryPath)
	if err != nil {
		log.Fatalf("load inventory: %v", err)
	}
	if sshKey != "" {
		key, keyErr := expandHome(sshKey)
		if keyErr != nil {
			log.Fatalf("expand ssh key: %v", keyErr)
		}
		inv.SSHKey = key
	}

	client, err := porter.ConnectWithKey(inv.Host, inv.SSHUser, inv.SSHKey, 0)
	if err != nil {
		log.Fatalf("connect: %v", err)
	}
	defer client.Close()

	executor := porter.NewExecutor(client, "").SetDryRun(dryRun)
	vars := porter.NewVars()

	switch command {
	case "bootstrap":
		envContent, envErr := renderEnv(inv)
		if envErr != nil {
			log.Fatalf("render env: %v", envErr)
		}
		hysteriaContent, hysteriaEnabled, hysteriaErr := renderHysteriaClientYAML(inv)
		if hysteriaErr != nil {
			log.Fatalf("render hysteria config: %v", hysteriaErr)
		}
		stats, runErr := executor.Run(
			"Bootstrap Instrumenta",
			buildBootstrapTasks(inv, envContent, hysteriaContent, hysteriaEnabled),
			vars,
		)
		if runErr != nil {
			log.Fatalf("bootstrap failed: %v", runErr)
		}
		log.Printf("bootstrap complete: %d ok, %d changed, %d failed", stats.OK, stats.Changed, stats.Failed)
	case "update":
		stats, runErr := executor.Run("Update Instrumenta", buildUpdateTasks(inv), vars)
		if runErr != nil {
			log.Fatalf("update failed: %v", runErr)
		}
		log.Printf("update complete: %d ok, %d changed, %d failed", stats.OK, stats.Changed, stats.Failed)
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q (expected bootstrap or update)\n", command)
		os.Exit(2)
	}
}

func parseCLI(args []string) (command, inventoryPath, sshKey string, dryRun bool, err error) {
	inventoryPath = defaultInventoryPath

	if len(args) == 0 {
		return "", "", "", false, cliUsageError()
	}

	command = args[0]
	if command != "bootstrap" && command != "update" {
		return "", "", "", false, fmt.Errorf("unknown command %q\n%w", command, cliUsageError())
	}

	for i := 1; i < len(args); i++ {
		arg := args[i]
		switch arg {
		case "-dry-run":
			dryRun = true
		case "-inventory":
			if i+1 >= len(args) {
				return "", "", "", false, fmt.Errorf("-inventory requires a path\n%w", cliUsageError())
			}
			i++
			inventoryPath = args[i]
		case "-key":
			if i+1 >= len(args) {
				return "", "", "", false, fmt.Errorf("-key requires a path\n%w", cliUsageError())
			}
			i++
			sshKey = args[i]
		default:
			return "", "", "", false, fmt.Errorf("unknown argument %q\n%w", arg, cliUsageError())
		}
	}

	return command, inventoryPath, sshKey, dryRun, nil
}

func cliUsageError() error {
	return fmt.Errorf(
		"usage: %s <bootstrap|update> [-dry-run] [-inventory path] [-key path]",
		cliName(),
	)
}

func cliName() string {
	name := strings.TrimSpace(os.Args[0])
	if name == "" {
		return "deploy"
	}
	if strings.Contains(name, "/") {
		return name[strings.LastIndex(name, "/")+1:]
	}
	return name
}
