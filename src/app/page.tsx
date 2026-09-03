'use client';

import { useState, useRef, useEffect, useMemo } from 'react';
import { Upload, Download, Loader2, FlaskConical, Crown, Ship, Search } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { useToast } from '@/hooks/use-toast';
import {
  uploadSave, getMeta, getStats, getResources, getCountries, getFleets,
  updateResources, updateDate, updateName,
  exportSave, releaseSave, loadTestSave, getStatus,
} from '@/lib/save-api';
import type { SaveMeta, GameStats, ResourceInfo, ResourcesResponse, UploadResponse, CountryInfo, FleetInfo } from '@/lib/save-api';

type Screen = 'upload' | 'editor';

/** Human-readable labels for country types found in the gamestate. */
const COUNTRY_TYPE_LABELS: Record<string, string> = {
  default: '帝国',
  fallen_empire: '堕落帝国',
  awakened_fallen_empire: '觉醒帝国',
  primitive: '原始文明',
  dormant_marauders: '沉睡掠夺者',
  marauder_raiders: '掠夺者',
  enclave: '飞地',
  faction: '派系',
  neutral_faction: '中立派系',
  drone_faction: '机械派系',
  drone: '机械体',
  cloud: '虚空之云',
  amoeba: '太空变形虫',
  crystal: '水晶实体',
  tiyanki: '缇扬基',
  tiyanki_garrison: '缇扬基驻守',
  vluur: '弗鲁尔',
  shroud: '虚境',
  shroud_spirits: '虚境灵体',
  caravaneer_home: '商队之家',
  caravaneer_fleet: '商队舰队',
  enigmatic_cache: '神秘缓存',
  global_event: '全局事件',
};

function countryTypeLabel(type: string): string {
  if (COUNTRY_TYPE_LABELS[type]) return COUNTRY_TYPE_LABELS[type];
  if (type.startsWith('guardian')) return '守护者';
  return type || '未知';
}

/** Optgroup bucket for the country selector. */
function countryGroup(c: CountryInfo, playerId: string): string {
  if (c.id === playerId) return '玩家帝国';
  switch (c.type) {
    case 'default': return '常规帝国';
    case 'fallen_empire':
    case 'awakened_fallen_empire': return '堕落帝国';
    case 'primitive': return '原始文明';
    default: return '其他实体';
  }
}

const GROUP_ORDER = ['玩家帝国', '常规帝国', '堕落帝国', '原始文明', '其他实体'];

export default function Home() {
  const [screen, setScreen] = useState<Screen>('upload');
  const [loading, setLoading] = useState(false);
  const [filename, setFilename] = useState('');
  const [meta, setMeta] = useState<SaveMeta | null>(null);
  const [stats, setStats] = useState<GameStats | null>(null);
  const [resources, setResources] = useState<Record<string, ResourceInfo> | null>(null);
  const [resourceCategories, setResourceCategories] = useState<Record<string, string[]> | null>(null);
  const [editDate, setEditDate] = useState('');
  const [editName, setEditName] = useState('');
  const [editResources, setEditResources] = useState<Record<string, string>>({});
  const [splitInfo, setSplitInfo] = useState<Record<string, number>>({});
  const [testSaveAvailable, setTestSaveAvailable] = useState(false);
  const [countries, setCountries] = useState<CountryInfo[]>([]);
  const [countriesLoading, setCountriesLoading] = useState(false);
  const [countriesError, setCountriesError] = useState<string | null>(null);
  const [selectedCountryId, setSelectedCountryId] = useState('');
  const [fleets, setFleets] = useState<FleetInfo[]>([]);
  const [fleetsLoading, setFleetsLoading] = useState(false);
  const [fleetsError, setFleetsError] = useState<string | null>(null);
  const [fleetQuery, setFleetQuery] = useState('');
  const [fleetFilter, setFleetFilter] = useState<'all' | 'mobile' | 'station'>('all');
  const fileRef = useRef<HTMLInputElement>(null);
  /** Request-generation guards: discard stale async responses. */
  const countriesReqRef = useRef(0);
  const resourcesReqRef = useRef('');
  const fleetsReqRef = useRef('');
  const { toast } = useToast();

  // Detect whether the backend has a server-side test save configured
  // (TEST_SAVE env var) - enables the one-click test loader button.
  useEffect(() => {
    let cancelled = false;
    getStatus()
      .then((s) => { if (!cancelled) setTestSaveAvailable(!!s.test_save?.available); })
      .catch(() => { /* backend down: keep the file-upload flow */ });
    return () => { cancelled = true; };
  }, []);

  /**
   * Fetch the country list in the background. /api/countries long-polls
   * server-side until the full gamestate parse completes (~1 min for 44MB),
   * so this must never block the editor render. Retries on failure.
   */
  const startCountriesFetch = () => {
    const reqId = ++countriesReqRef.current;
    setCountriesLoading(true);
    setCountriesError(null);
    const attempt = async (n: number): Promise<void> => {
      try {
        const res = await getCountries();
        if (reqId !== countriesReqRef.current) return; // stale (released / re-upload)
        setCountries(res.countries);
        setCountriesLoading(false);
      } catch (err: any) {
        if (reqId !== countriesReqRef.current) return;
        if (n < 3) {
          await new Promise((r) => setTimeout(r, 5000));
          return attempt(n + 1);
        }
        setCountriesError(err.message || '国家列表加载失败');
        setCountriesLoading(false);
      }
    };
    attempt(0).catch(() => {});
  };

  /** Fetch the fleet list for a country (split-file fast path). */
  const startFleetsFetch = (countryId: string) => {
    const reqId = countryId;
    fleetsReqRef.current = reqId;
    setFleetsLoading(true);
    setFleetsError(null);
    getFleets(countryId)
      .then((r) => {
        if (fleetsReqRef.current !== reqId) return; // stale
        setFleets(r.fleets);
        setFleetsLoading(false);
      })
      .catch((err: any) => {
        if (fleetsReqRef.current !== reqId) return;
        setFleetsError(err.message || '舰队列表加载失败');
        setFleetsLoading(false);
      });
  };

  /** Shared post-upload flow: fetch stats + resources and enter the editor. */
  const applyUpload = async (res: UploadResponse) => {
    setFilename(res.filename);
    setMeta(res.meta);
    setEditName(res.meta.name);
    setSplitInfo(res.split_info ?? {});
    setSelectedCountryId(res.player_country_id);
    resourcesReqRef.current = res.player_country_id;
    setCountries([]);
    setFleets([]);
    setFleetQuery('');
    setFleetFilter('all');
    const [s, r] = await Promise.all([getStats(), getResources(res.player_country_id)]);
    setStats(s);
    setResources(r.resources);
    setResourceCategories(r.categories);
    setEditDate(s.date);
    const init: Record<string, string> = {};
    for (const [k, v] of Object.entries(r.resources)) init[k] = String(v.value);
    setEditResources(init);
    setScreen('editor');
    // Country list arrives later (needs the background full parse).
    startCountriesFetch();
    // Fleet list is split-file fast - load right away.
    startFleetsFetch(res.player_country_id);
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    try {
      const res = await uploadSave(file);
      await applyUpload(res);
      toast({ title: '上传成功', description: `${res.meta.name} (${res.meta.date})` });
    } catch (err: any) {
      toast({ title: '上传失败', description: err.message, variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  /** Load the backend-side test save via POST /api/test/load (no file input). */
  const handleLoadTestSave = async () => {
    setLoading(true);
    try {
      const res = await loadTestSave();
      await applyUpload(res);
      toast({ title: '测试存档已加载', description: `${res.meta.name} (${res.meta.date})` });
    } catch (err: any) {
      toast({ title: '加载测试存档失败', description: err.message, variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  /** Switch the edited country: refetch its resources + fleets from the backend. */
  const handleSelectCountry = async (id: string) => {
    if (!id || id === selectedCountryId) return;
    setSelectedCountryId(id);
    resourcesReqRef.current = id;
    setEditResources({}); // clear stale inputs while loading
    setFleets([]);
    setFleetQuery('');
    setFleetFilter('all');
    startFleetsFetch(id);
    try {
      const r = await getResources(id);
      if (resourcesReqRef.current !== id) return; // user switched again
      setResources(r.resources);
      setResourceCategories(r.categories);
      const init: Record<string, string> = {};
      for (const [k, v] of Object.entries(r.resources)) init[k] = String(v.value);
      setEditResources(init);
    } catch (err: any) {
      if (resourcesReqRef.current === id) {
        toast({ title: '加载国家资源失败', description: err.message, variant: 'destructive' });
      }
    }
  };

  const handleSaveResources = async () => {
    if (!resources) return;
    const targetId = selectedCountryId || stats?.player_country_id || '0';
    const nums: Record<string, number> = {};
    for (const [k, v] of Object.entries(editResources)) {
      const n = Number(v);
      if (!isNaN(n)) nums[k] = n;
    }
    try {
      await updateResources(targetId, nums);
      const r = await getResources(targetId);
      if (resourcesReqRef.current === targetId) {
        setResources(r.resources);
        const init: Record<string, string> = {};
        for (const [k, v] of Object.entries(r.resources)) init[k] = String(v.value);
        setEditResources(init);
      }
      const target = countries.find((c) => c.id === targetId);
      toast({ title: '资源已保存', description: target ? `${target.name} (${targetId}) 的资源已更新` : undefined });
    } catch (err: any) {
      toast({ title: '保存失败', description: err.message, variant: 'destructive' });
    }
  };

  const handleSaveDate = async () => {
    try {
      const r = await updateDate(editDate);
      setEditDate(r.date);
      if (stats) setStats({ ...stats, date: r.date });
      toast({ title: '日期已更新' });
    } catch (err: any) {
      toast({ title: '更新失败', description: err.message, variant: 'destructive' });
    }
  };

  const handleSaveName = async () => {
    try {
      await updateName(editName);
      if (meta) setMeta({ ...meta, name: editName });
      toast({ title: '名称已更新' });
    } catch (err: any) {
      toast({ title: '更新失败', description: err.message, variant: 'destructive' });
    }
  };

  const handleExport = async () => {
    try {
      const blob = await exportSave();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename.replace(/\.sav$/, '_edited.sav');
      a.click();
      URL.revokeObjectURL(url);
      toast({ title: '导出成功' });
    } catch (err: any) {
      toast({ title: '导出失败', description: err.message, variant: 'destructive' });
    }
  };

  const handleRelease = async () => {
    await releaseSave();
    countriesReqRef.current++; // discard in-flight country list request
    resourcesReqRef.current = '';
    fleetsReqRef.current = '';
    setScreen('upload');
    setMeta(null);
    setStats(null);
    setResources(null);
    setEditResources({});
    setSplitInfo({});
    setCountries([]);
    setSelectedCountryId('');
    setCountriesError(null);
    setCountriesLoading(false);
    setFleets([]);
    setFleetsError(null);
    setFleetsLoading(false);
    setFleetQuery('');
    setFleetFilter('all');
    if (fileRef.current) fileRef.current.value = '';
  };

  // Grouped + power-sorted options for the country selector.
  const groupedCountries = useMemo(() => {
    const playerId = stats?.player_country_id ?? '';
    const groups: Record<string, CountryInfo[]> = {};
    for (const c of countries) {
      const g = countryGroup(c, playerId);
      (groups[g] ??= []).push(c);
    }
    for (const list of Object.values(groups)) {
      list.sort((a, b) => b.military_power - a.military_power);
    }
    return groups;
  }, [countries, stats]);

  const selectedCountry = countries.find((c) => c.id === selectedCountryId) ?? null;
  const isPlayerCountry = !!stats && selectedCountryId === stats.player_country_id;

  // Fleet list: search + type filter (backend pre-sorts: mobile by mp
  // desc, then stations).
  const filteredFleets = useMemo(() => {
    const q = fleetQuery.trim().toLowerCase();
    return fleets.filter((f) => {
      if (fleetFilter === 'mobile' && f.station) return false;
      if (fleetFilter === 'station' && !f.station) return false;
      if (q && !f.name.toLowerCase().includes(q) && !f.id.includes(q)) return false;
      return true;
    });
  }, [fleets, fleetQuery, fleetFilter]);

  const fleetCounts = useMemo(() => ({
    mobile: fleets.filter((f) => !f.station).length,
    station: fleets.filter((f) => f.station).length,
  }), [fleets]);

  if (screen === 'upload') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <Card className="w-full max-w-md">
          <CardHeader className="text-center">
            <CardTitle className="text-2xl">群星存档修改器</CardTitle>
            <p className="text-sm text-muted-foreground mt-1">
              Stellaris Save Editor
            </p>
          </CardHeader>
          <CardContent>
            <label className="flex flex-col items-center gap-4 cursor-pointer">
              <div className="w-full h-32 border-2 border-dashed rounded-lg flex items-center justify-center hover:border-primary/50 transition-colors">
                {loading ? (
                  <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                ) : (
                  <div className="text-center">
                    <Upload className="h-8 w-8 mx-auto mb-2 text-muted-foreground" />
                    <p className="text-sm text-muted-foreground">点击或拖拽 .sav 文件</p>
                  </div>
                )}
              </div>
              <input
                ref={fileRef}
                type="file"
                accept=".sav"
                className="hidden"
                onChange={handleUpload}
                disabled={loading}
              />
            </label>
            {testSaveAvailable && (
              <>
                <div className="flex items-center gap-3 mt-4">
                  <Separator className="flex-1" />
                  <span className="text-xs text-muted-foreground">或</span>
                  <Separator className="flex-1" />
                </div>
                <Button
                  variant="outline"
                  className="w-full mt-3"
                  onClick={handleLoadTestSave}
                  disabled={loading}
                >
                  <FlaskConical className="h-4 w-4 mr-2" />
                  加载服务器测试存档
                </Button>
                <p className="text-xs text-muted-foreground mt-2 text-center">
                  直接从后端加载 TEST_SAVE 指定的存档，无需选择文件
                </p>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background p-4 md:p-8">
      <div className="max-w-4xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold">{meta?.name}</h1>
            <p className="text-sm text-muted-foreground">
              {meta?.date} | {stats?.num_countries} 国家 | {stats?.num_species} 物种
              {Object.keys(splitInfo).length > 0 && (
                <span className="ml-2 text-muted-foreground/60">
                  (预拆分: {Object.entries(splitInfo).map(([k, v]) => `${k}×${v}`).join(' / ')})
                </span>
              )}
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={handleExport}>
              <Download className="h-4 w-4 mr-1" />导出
            </Button>
            <Button variant="outline" size="sm" onClick={handleRelease}>
              释放存档
            </Button>
          </div>
        </div>

        {/* Country selector */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <CardTitle className="text-base">国家选择</CardTitle>
              {countriesLoading && (
                <span className="text-xs text-muted-foreground flex items-center gap-1">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  国家列表解析中（后台全量解析）…
                </span>
              )}
              {countriesError && (
                <span className="text-xs text-red-500" title={countriesError}>国家列表加载失败（可重试上传）</span>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <select
              id="country-select"
              aria-label="选择国家"
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              value={selectedCountryId}
              onChange={(e) => handleSelectCountry(e.target.value)}
              disabled={countries.length === 0}
            >
              {countries.length === 0 ? (
                <option value={selectedCountryId}>
                  {countriesLoading ? '国家列表解析中…' : '国家列表不可用'}
                </option>
              ) : (
                GROUP_ORDER
                  .filter((g) => groupedCountries[g]?.length)
                  .map((g) => (
                    <optgroup key={g} label={`${g}（${groupedCountries[g].length}）`}>
                      {groupedCountries[g].map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name || `（国家 ${c.id}）`}
                        </option>
                      ))}
                    </optgroup>
                  ))
              )}
            </select>
            {selectedCountry && (
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <Badge variant={isPlayerCountry ? 'default' : 'secondary'} className="gap-1">
                  {isPlayerCountry && <Crown className="h-3 w-3" />}
                  {countryTypeLabel(selectedCountry.type)}
                </Badge>
                <span>ID {selectedCountry.id}</span>
                <span>军事 {Math.round(selectedCountry.military_power).toLocaleString()}</span>
                <span>经济 {Math.round(selectedCountry.economy_power).toLocaleString()}</span>
                <span>科技 {Math.round(selectedCountry.tech_power).toLocaleString()}</span>
                <span>舰队 {selectedCountry.fleet_size}</span>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Fleet list viewer */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <div className="flex items-center gap-2">
                <CardTitle className="text-base flex items-center gap-1.5">
                  <Ship className="h-4 w-4" />舰队列表
                </CardTitle>
                {selectedCountry && (
                  <span className="text-sm text-muted-foreground">— {selectedCountry.name}</span>
                )}
              </div>
              {fleetsLoading ? (
                <span className="text-xs text-muted-foreground flex items-center gap-1">
                  <Loader2 className="h-3 w-3 animate-spin" />加载中…
                </span>
              ) : (
                <span className="text-xs text-muted-foreground">
                  {fleetCounts.mobile} 舰队 / {fleetCounts.station} 空间站
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <div className="relative flex-1 min-w-[180px]">
                <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
                <Input
                  className="h-8 pl-8 text-sm"
                  placeholder="搜索舰队名称或 ID…"
                  value={fleetQuery}
                  onChange={(e) => setFleetQuery(e.target.value)}
                />
              </div>
              <div className="flex gap-1">
                {([['all', `全部 ${fleets.length}`], ['mobile', `舰队 ${fleetCounts.mobile}`], ['station', `空间站 ${fleetCounts.station}`]] as const).map(([key, label]) => (
                  <Button
                    key={key}
                    size="sm"
                    variant={fleetFilter === key ? 'default' : 'outline'}
                    className="h-8 text-xs"
                    onClick={() => setFleetFilter(key)}
                  >
                    {label}
                  </Button>
                ))}
              </div>
            </div>
            {fleetsError && (
              <p className="text-xs text-red-500">{fleetsError}</p>
            )}
          </CardHeader>
          <CardContent>
            {fleets.length > 0 ? (
              <div className="rounded-md border max-h-96 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-muted/95 backdrop-blur">
                    <tr className="text-left text-muted-foreground">
                      <th className="px-3 py-2 font-medium">名称</th>
                      <th className="px-3 py-2 font-medium w-14">类型</th>
                      <th className="px-3 py-2 font-medium w-14 text-right">舰船</th>
                      <th className="px-3 py-2 font-medium w-20 text-right">军力</th>
                      <th className="px-3 py-2 font-medium w-20 text-right">舰体</th>
                      <th className="px-3 py-2 font-medium w-20">状态</th>
                      <th className="px-3 py-2 font-medium w-28 text-right">坐标</th>
                      <th className="px-3 py-2 font-medium w-12 text-right">ID</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredFleets.map((f) => (
                      <tr key={f.id} className="border-t hover:bg-muted/50">
                        <td className="px-3 py-1.5 max-w-[220px] truncate" title={f.name}>{f.name || `（舰队 ${f.id}）`}</td>
                        <td className="px-3 py-1.5">
                          {f.station ? (
                            <Badge variant="secondary" className="text-[10px] px-1.5">空间站</Badge>
                          ) : f.civilian ? (
                            <Badge variant="outline" className="text-[10px] px-1.5">民用</Badge>
                          ) : (
                            <Badge variant="default" className="text-[10px] px-1.5">舰队</Badge>
                          )}
                        </td>
                        <td className="px-3 py-1.5 text-right tabular-nums">{f.ship_count}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums">{f.military_power >= 1000 ? `${(f.military_power / 1000).toFixed(1)}k` : Math.round(f.military_power)}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums">{f.hit_points >= 1000 ? `${(f.hit_points / 1000).toFixed(0)}k` : Math.round(f.hit_points)}</td>
                        <td className="px-3 py-1.5 text-muted-foreground" title={f.movement_state}>{f.movement_state.replace(/^move_/, '') || '—'}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                          {f.coordinate ? `(${Math.round(f.coordinate.x)}, ${Math.round(f.coordinate.y)})` : '—'}
                        </td>
                        <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground" title={`ownership: ${f.ownership_status}`}>{f.id}</td>
                      </tr>
                    ))}
                    {filteredFleets.length === 0 && (
                      <tr><td colSpan={8} className="px-3 py-6 text-center text-muted-foreground">无匹配舰队</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground py-4 text-center">
                {fleetsLoading ? '舰队列表加载中…' : fleetsError ? '加载失败' : '该国家暂无舰队数据'}
              </p>
            )}
          </CardContent>
        </Card>

        {/* Date & Name */}
        <Card>
          <CardContent className="pt-6 grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>游戏日期</Label>
              <div className="flex gap-2">
                <Input value={editDate} onChange={(e) => setEditDate(e.target.value)} placeholder="2200.01.01" />
                <Button size="sm" onClick={handleSaveDate}>保存</Button>
              </div>
            </div>
            <div className="space-y-2">
              <Label>帝国名称</Label>
              <div className="flex gap-2">
                <Input value={editName} onChange={(e) => setEditName(e.target.value)} />
                <Button size="sm" onClick={handleSaveName}>保存</Button>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Resources */}
        {resourceCategories && resources && (
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="flex items-center gap-2 flex-wrap">
                  <CardTitle className="text-base">资源编辑</CardTitle>
                  {selectedCountry && (
                    <span className="text-sm text-muted-foreground">— {selectedCountry.name}</span>
                  )}
                </div>
                <Button size="sm" onClick={handleSaveResources}>保存全部</Button>
              </div>
              {selectedCountry && !isPlayerCountry && (
                <p className="text-xs text-amber-600">正在编辑非玩家国家的资源，保存后写入该国的存档数据</p>
              )}
            </CardHeader>
            <CardContent className="space-y-4">
              {Object.entries(resourceCategories).map(([cat, keys]) => (
                <div key={cat}>
                  <h3 className="text-sm font-medium text-muted-foreground mb-2">{cat}</h3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                    {keys.map((key) => {
                      const info = resources[key];
                      if (!info) return null;
                      return (
                        <div key={key} className="flex items-center gap-2">
                          <Label className="text-xs w-20 shrink-0 truncate" title={info.label}>
                            {info.label}
                          </Label>
                          <Input
                            className="h-8 text-sm"
                            value={editResources[key] ?? ''}
                            onChange={(e) => setEditResources((p) => ({ ...p, [key]: e.target.value }))}
                          />
                          {info.income !== 0 && (
                            <span className={`text-xs w-16 text-right shrink-0 ${info.income >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                              {info.income >= 0 ? '+' : ''}{info.income}
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
