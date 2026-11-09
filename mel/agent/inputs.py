"""What the agent needs besides the insight: the farmer's profile and chat hours. Owner: P5.
Loads the full participant pack when it is in the repo (MEL_DATA_DIR still wins), else the mock sample."""

from collections import defaultdict

from mel.config import PACK_DATA, full_pack


class Pack:
    def __init__(self, insights=None, farmers=None):
        from mel.data import load_insights, load_farmers

        full = full_pack()
        self.insights = (
            insights if insights is not None else load_insights(PACK_DATA / "insights.jsonl" if full else None)
        )
        self.farmers = farmers if farmers is not None else load_farmers(PACK_DATA / "farmers.csv" if full else None)
        self.by_id = {i.get("insight_id"): i for i in self.insights}
        self._by_farmer = defaultdict(list)
        for i in self.insights:
            self._by_farmer[i.get("farmer_id")].append(i)

    def inputs_for(self, ins: dict) -> dict:
        """`farmer` and `history_hours` for run_agent, the same way run_pipeline computes them."""
        from mel.timing import chat_hours

        fid = ins.get("farmer_id")
        return {
            "farmer": self.farmers.get(fid),
            "history_hours": chat_hours(self._by_farmer[fid], fid, ins.get("created_at")),
        }
