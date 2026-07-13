// Package simulation implements event-sourced portfolio cashflow simulation.
//
// Go disallows import cycles between this package and portfolio models, so the
// implementation lives in the parent portfolio package:
//   - simulation_state.go  (OpenPosition, PortfolioState)
//   - simulation_events.go (SimEvent, ScheduledEvent)
//   - simulation_engine.go (RunSimulation)
//
// API consumers should call portfolio.RunSimulation and portfolio.BuildPlan.
package simulation
