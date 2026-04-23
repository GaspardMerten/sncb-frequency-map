import { rootRoute } from "./routes/__root";
import { indexRoute } from "./routes/index";
import { segmentsRoute } from "./routes/segments";
import { reachRoute } from "./routes/reach";
import { rankingsRoute } from "./routes/rankings";
import { connectivityRoute } from "./routes/connectivity";
import { durationRoute } from "./routes/duration";
import { multimodalRoute } from "./routes/multimodal";
import { punctualityRoute } from "./routes/punctuality";
import { accessibilityRoute } from "./routes/accessibility";
import { propagationRoute } from "./routes/propagation";
import { problematicRoute } from "./routes/problematic";
import { missedRoute } from "./routes/missed";
import { weatherRoute } from "./routes/weather";
import { deletedRoute } from "./routes/deleted";
import { reportMissedRoute } from "./routes/report-missed";

export const routeTree = rootRoute.addChildren([
  indexRoute,
  segmentsRoute,
  reachRoute,
  rankingsRoute,
  connectivityRoute,
  durationRoute,
  multimodalRoute,
  punctualityRoute,
  accessibilityRoute,
  propagationRoute,
  problematicRoute,
  missedRoute,
  weatherRoute,
  deletedRoute,
  reportMissedRoute,
]);
