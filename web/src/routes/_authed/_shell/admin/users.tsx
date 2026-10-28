import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { Check, Copy, Link2, Plus, UserCog } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, errorMessage, type Schemas } from "@/api/client";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { ErrorState, PageHeader } from "@/components/common/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { format } from "@/i18n";
import { useAccount } from "@/lib/account";

type User = Schemas["UserAdminOut"];
const ROLES = ["admin", "user", "guest"] as const;

export const Route = createFileRoute("/_authed/_shell/admin/users")({
  component: Users,
});

function Users() {
  const { t } = useTranslation();
  const users = api.useQuery("get", "/api/admin/users");
  return (
    <div>
      <PageHeader title={t("admin.nav.users")} description={t("users.intro")} actions={<UserDialog />} />
      {users.isError ? (
        <ErrorState error={users.error} onRetry={() => void users.refetch()} />
      ) : users.isPending ? (
        <Skeleton className="h-48 rounded-xl" />
      ) : (
        <div className="rounded-xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("auth.username")}</TableHead>
                <TableHead>{t("users.role")}</TableHead>
                <TableHead className="hidden sm:table-cell">{t("users.login")}</TableHead>
                <TableHead className="hidden md:table-cell">{t("users.lastLogin")}</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.data.map((user) => (
                <TableRow key={user.id} className={user.disabled ? "opacity-60" : undefined}>
                  <TableCell>
                    <div className="font-medium">{user.username}</div>
                    {user.email && <div className="text-xs text-muted-foreground">{user.email}</div>}
                  </TableCell>
                  <TableCell>
                    <Badge variant={user.role === "admin" ? "default" : "secondary"}>{t(`account.roles.${user.role as "admin"}`)}</Badge>
                    {user.disabled && <Badge variant="outline" className="ml-1">{t("users.disabled")}</Badge>}
                  </TableCell>
                  <TableCell className="hidden text-xs text-muted-foreground sm:table-cell">
                    {[user.has_password && t("users.password"), user.passkeys > 0 && t("users.passkeys", { count: user.passkeys }), user.oidc && t("users.oidc")].filter(Boolean).join(", ") || t("users.noLogin")}
                    {user.two_factor && <Badge variant="outline" className="ml-1.5">{t("users.twoStep")}</Badge>}
                  </TableCell>
                  <TableCell className="hidden text-xs text-muted-foreground md:table-cell">{user.last_login_at ? format.relative(user.last_login_at) : t("common.never")}</TableCell>
                  <TableCell><UserDialog user={user} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function UserDialog({ user }: { user?: User }) {
  const { t } = useTranslation();
  const account = useAccount();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [role, setRole] = useState<string>(user?.role ?? "user");
  const [disabled, setDisabled] = useState(user?.disabled ?? false);
  const create = api.useMutation("post", "/api/admin/users");
  const update = api.useMutation("patch", "/api/admin/users/{user_id}");
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password") ?? "");
    const email = String(form.get("email") ?? "").trim() || null;
    try {
      if (user) {
        await update.mutateAsync({ params: { path: { user_id: user.id } }, body: { email, role: role as User["role"], disabled, ...(password ? { password } : {}) } as never });
      } else {
        await create.mutateAsync({ body: { username: String(form.get("username")), email, role: role as never, password: password || null } });
      }
      toast.success(t("common.saved"));
      setOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["get", "/api/admin/users"] });
    } catch (error) {
      toast.error(errorMessage(error, t("common.errorGeneric")));
    }
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={user ? <Button variant="ghost" size="icon-sm" aria-label={t("users.edit", { name: user.username })} /> : <Button size="sm" />}>
        {user ? <UserCog aria-hidden /> : <><Plus aria-hidden />{t("users.new")}</>}
      </DialogTrigger>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{user ? t("users.edit", { name: user.username }) : t("users.new")}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-4">
          {!user && (
            <div className="space-y-1.5">
              <Label htmlFor="user-name">{t("auth.username")}</Label>
              <Input id="user-name" name="username" required autoComplete="off" />
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="user-email">{t("auth.email")}</Label>
            <Input id="user-email" name="email" type="email" defaultValue={user?.email ?? ""} />
          </div>
          <div className="space-y-1.5">
            <Label>{t("users.role")}</Label>
            <Select value={role} onValueChange={(v) => setRole(String(v))}>
              <SelectTrigger className="w-full" aria-label={t("users.role")}>
                <SelectValue>{(v: string) => t(`account.roles.${v as "admin"}`)}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {ROLES.map((r) => <SelectItem key={r} value={r}>{t(`account.roles.${r}`)}</SelectItem>)}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">{t(`users.roleHints.${role as "admin"}`)}</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="user-password">{user ? t("users.newPassword") : t("users.passwordOptional")}</Label>
            <Input id="user-password" name="password" type="password" minLength={8} autoComplete="new-password" />
            <p className="text-xs text-muted-foreground">{user ? t("users.newPasswordHint") : t("users.passwordHint")}</p>
          </div>
          {user && <SignInLink user={user} />}
          {user && (user.two_factor || user.passkeys > 0) && <ResetTwoStep user={user} />}
          {user && user.id !== account.id && (
            <label className="flex items-start justify-between gap-4">
              <span><span className="block text-sm font-medium">{t("users.disable")}</span><span className="block text-xs text-muted-foreground">{t("users.disableHint")}</span></span>
              <Switch checked={disabled} onCheckedChange={setDisabled} />
            </label>
          )}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
            <Button type="submit" disabled={create.isPending || update.isPending}>{user ? t("common.save") : t("common.create")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** A one-time link for setting a password, to hand over in person or by message. */
function SignInLink({ user }: { user: User }) {
  const { t } = useTranslation();
  const make = api.useMutation("post", "/api/admin/users/{user_id}/sign-in-link");
  const [copied, setCopied] = useState(false);
  return (
    <div className="space-y-1.5 rounded-lg border p-3">
      <div className="flex items-center justify-between gap-3">
        <span>
          <span className="block text-sm font-medium">{t("users.link.title")}</span>
          <span className="block text-xs text-muted-foreground">{t("users.link.hint")}</span>
        </span>
        <Button type="button" size="sm" variant="outline" disabled={make.isPending} onClick={() => make.mutate({ params: { path: { user_id: user.id } } })}>
          <Link2 aria-hidden />
          {make.data ? t("users.link.again") : t("users.link.make")}
        </Button>
      </div>
      {make.data && (
        <div className="space-y-1">
          <div className="flex gap-2">
            <Input readOnly value={make.data.url} className="font-mono text-xs" aria-label={t("users.link.title")} onFocus={(e) => e.currentTarget.select()} />
            <Button type="button" variant="outline" size="sm" onClick={() => void navigator.clipboard.writeText(make.data.url).then(() => setCopied(true))}>
              {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
              {copied ? t("common.copied") : t("common.copy")}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">{t("users.link.until", { when: format.date(make.data.expires_at, { dateStyle: "medium", timeStyle: "short" }) })}</p>
        </div>
      )}
    </div>
  );
}

function ResetTwoStep({ user }: { user: User }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const reset = api.useMutation("post", "/api/admin/users/{user_id}/reset-two-factor", {
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["get", "/api/admin/users"] }),
  });
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border p-3">
      <span>
        <span className="block text-sm font-medium">{t("users.reset.title")}</span>
        <span className="block text-xs text-muted-foreground">{t("users.reset.hint")}</span>
      </span>
      <ConfirmDialog
        trigger={<Button type="button" size="sm" variant="outline">{t("users.reset.short")}</Button>}
        title={t("users.reset.confirmTitle", { name: user.username })}
        description={t("users.reset.confirmText")}
        confirm={t("users.reset.short")}
        onConfirm={async () => {
          await reset.mutateAsync({ params: { path: { user_id: user.id } } });
          toast.success(t("users.reset.done", { name: user.username }));
        }}
      />
    </div>
  );
}
