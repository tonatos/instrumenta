package billing

// Feature is a gateable capability. New paid capabilities extend this list
// and are attached to plan versions — no architecture change required.
type Feature string

const (
	FeatureBrokerCredentialsWrite Feature = "broker_credentials.write"
	FeaturePortfolioAttach        Feature = "portfolio.attach"
	FeatureTradingPortfolioAccess Feature = "trading_portfolio.access"
)

// PaidFeaturesV1 is the default feature set for the Pro plan.
func PaidFeaturesV1() []Feature {
	return []Feature{
		FeatureBrokerCredentialsWrite,
		FeaturePortfolioAttach,
		FeatureTradingPortfolioAccess,
	}
}

// HasFeature reports whether feature is present in the list.
func HasFeature(features []Feature, feature Feature) bool {
	for _, f := range features {
		if f == feature {
			return true
		}
	}
	return false
}
