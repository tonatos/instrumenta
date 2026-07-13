package portfolio

import "github.com/tonatos/bond-monitor/backend/internal/domain/bonds"

// OpenPosition tracks one open lot with lifecycle metadata.
type OpenPosition struct {
	Position   PortfolioPosition
	Generation int
	Closed     bool
}

// PortfolioState is the write-model while simulating cashflow.
type PortfolioState struct {
	Cash          float64
	OpenPositions []OpenPosition
	AllPositions  []PortfolioPosition
	nextID        int64
}

func NewPortfolioState(cash float64) *PortfolioState {
	return &PortfolioState{Cash: cash, nextID: 1}
}

func (s *PortfolioState) LotsByISIN() map[string]int {
	lots := make(map[string]int)
	for _, entry := range s.OpenPositions {
		if entry.Closed {
			continue
		}
		lots[entry.Position.ISIN] += entry.Position.Lots
	}
	return lots
}

func (s *PortfolioState) HoldingsValue(universeByISIN map[string]bonds.BondRecord) float64 {
	var total float64
	for isin, lots := range s.LotsByISIN() {
		bond, ok := universeByISIN[isin]
		if !ok {
			continue
		}
		if p := bond.PricePerLotRub(); p != nil && *p > 0 {
			total += float64(lots) * *p
		}
	}
	return total
}

func (s *PortfolioState) IsOpen(positionID int64) bool {
	for _, entry := range s.OpenPositions {
		if entry.Position.ID == positionID {
			return !entry.Closed
		}
	}
	return false
}

func (s *PortfolioState) ClosePosition(positionID int64) {
	for i := range s.OpenPositions {
		if s.OpenPositions[i].Position.ID == positionID {
			s.OpenPositions[i].Closed = true
			return
		}
	}
}

func (s *PortfolioState) AddPosition(position PortfolioPosition, generation int) *OpenPosition {
	position.ID = s.nextID
	s.nextID++
	entry := &OpenPosition{Position: position, Generation: generation}
	s.OpenPositions = append(s.OpenPositions, *entry)
	s.AllPositions = append(s.AllPositions, position)
	return entry
}
