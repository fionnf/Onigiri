import { ApiError, api } from "@/api/client";
import { Shell } from "@/components/Shell";
import { Spinner } from "@/components/ui";
import { Add } from "@/routes/Add";
import { Cook } from "@/routes/Cook";
import { JobView } from "@/routes/JobView";
import { Library } from "@/routes/Library";
import { Login } from "@/routes/Login";
import { ProfilePage } from "@/routes/ProfilePage";
import { RecipeEdit } from "@/routes/RecipeEdit";
import { RecipeView } from "@/routes/RecipeView";
import { Settings } from "@/routes/Settings";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate, Route, Routes } from "react-router-dom";

export function App() {
  const queryClient = useQueryClient();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    retry: (count, error) => !(error instanceof ApiError && error.status === 401) && count < 2,
  });

  if (me.isLoading) {
    return (
      <div className="flex min-h-full items-center justify-center">
        <Spinner label="Opening Onigiri…" />
      </div>
    );
  }

  if (me.isError) {
    return <Login onSignedIn={() => queryClient.invalidateQueries()} />;
  }

  return (
    <Routes>
      {/* Cooking takes the whole screen, so it sits outside the shell. */}
      <Route path="/r/:recipeId/cook" element={<Cook />} />
      <Route
        path="*"
        element={
          <Shell>
            <Routes>
              <Route path="/" element={<Library />} />
              <Route path="/add" element={<Add />} />
              <Route path="/j/:jobId" element={<JobView />} />
              <Route path="/r/:recipeId" element={<RecipeView />} />
              <Route path="/r/:recipeId/edit" element={<RecipeEdit />} />
              <Route path="/profile" element={<ProfilePage />} />
              <Route
                path="/settings"
                element={<Settings onSignedOut={() => queryClient.clear()} />}
              />
              <Route path="/share-target" element={<Navigate to="/add?shared=1" replace />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Shell>
        }
      />
    </Routes>
  );
}
