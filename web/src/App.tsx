import { ApiError, api } from "@/api/client";
import { Shell } from "@/components/Shell";
import { Spinner } from "@/components/ui";
import { warmOfflineCache } from "@/lib/offline";
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
import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

export function App() {
  const queryClient = useQueryClient();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    retry: (count, error) => !(error instanceof ApiError && error.status === 401) && count < 2,
  });

  // Keep recent recipes on the phone for the kitchen, once signed in and online.
  useEffect(() => {
    if (me.data) void warmOfflineCache().catch(() => {});
  }, [me.data]);

  if (me.isLoading) {
    return (
      <div className="flex min-h-full items-center justify-center">
        <Spinner label="Opening Onigiri…" />
      </div>
    );
  }

  // Only the server saying "not signed in" shows the sign-in page. Without a
  // connection the app opens anyway and shows what is saved on the phone.
  if (me.isError && me.error instanceof ApiError && me.error.status === 401) {
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
                element={
                  <Settings
                    onSignedOut={() => {
                      // A clean reload drops every in-memory copy and lands on sign-in.
                      queryClient.clear();
                      window.location.assign("/");
                    }}
                  />
                }
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
