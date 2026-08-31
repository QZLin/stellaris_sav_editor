'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import {
  Upload, FileText, Download, RotateCcw, Save,
  ChevronRight, Star, Globe, Users, Dna, Calendar,
  Zap, Gem, Wheat, FlaskConical, Cog, Crown, Sparkles,
  Monitor, Wrench, Wind, TestTubes, Diamond, Moon,
  Amphora, Orbit, Bot, AlertTriangle, Check, Loader2,
  Shield, Swords, Rocket, MapPin, BookOpen, Flag,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Label } from '@/components/ui/label';
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog';
import { useToast } from '@/hooks/use-toast';
import {
  type SaveMeta, type GameStats, type ResourceInfo,
  type CountryInfo, type SpeciesInfo, type ResourceCategory,
  uploadSave, getMeta, getStats, getResources, getCountries,
  getSpecies, updateResources, updateDate, updateName,
  exportSave, releaseSave,
} from '@/lib/save-api';

// ============ ICON MAPPING ============
const RESOURCE_ICON_MAP: Record<string, React.ReactNode> = {
  energy: <Zap className="h-4 w-4 text-yellow-400" />,
  minerals: <Gem className="h-4 w-4 text-cyan-400" />,
  food: <Wheat className="h-4 w-4 text-green-400" />,
  physics_research: <FlaskConical className="h-4 w-4 text-blue-400" />,
  society_research: <Dna className="h-4 w-4 text-green-300" />,
  engineering_research: <Cog className="h-4 w-4 text-orange-400" />,
  influence: <Crown className="h-4 w-4 text-purple-400" />,
  unity: <Sparkles className="h-4 w-4 text-amber-400" />,
  consumer_goods: <Monitor className="h-4 w-4 text-gray-300" />,
  alloys: <Wrench className="h-4 w-4 text-slate-300" />,
  volatile_motes: <Wind className="h-4 w-4 text-orange-300" />,
  exotic_gases: <TestTubes className="h-4 w-4 text-teal-400" />,
  rare_crystals: <Diamond className="h-4 w-4 text-pink-400" />,
  sr_dark_matter: <Moon className="h-4 w-4 text-indigo-400" />,
  minor_artifacts: <Amphora className="h-4 w-4 text-amber-600" />,
  sr_zro: <Orbit className="h-4 w-4 text-violet-400" />,
  nanites: <Bot className="h-4 w-4 text-emerald-400" />,
};

const CATEGORY_COLORS: Record<string, string> = {
  '基础资源': 'bg-yellow-500/10 text-yellow-300 border-yellow-500/20',
  '科研': 'bg-blue-500/10 text-blue-300 border-blue-500/20',
  '战略资源': 'bg-purple-500/10 text-purple-300 border-purple-500/20',
  '稀有资源': 'bg-orange-500/10 text-orange-300 border-orange-500/20',
  '高级资源': 'bg-pink-500/10 text-pink-300 border-pink-500/20',
};

// ============ MAIN COMPONENT ============
export default function StellarisSaveEditor() {
  const { toast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // State
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [meta, setMeta] = useState<SaveMeta | null>(null);
  const [stats, setStats] = useState<GameStats | null>(null);
  const [resources, setResources] = useState<Record<string, ResourceInfo>>({});
  const [resourceCategories, setResourceCategories] = useState<ResourceCategory>({});
  const [countries, setCountries] = useState<CountryInfo[]>([]);
  const [species, setSpecies] = useState<SpeciesInfo[]>([]);
  const [selectedCountry, setSelectedCountry] = useState('0');
  const [editName, setEditName] = useState('');
  const [editDate, setEditDate] = useState('');
  const [editResources, setEditResources] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [activeTab, setActiveTab] = useState('overview');

  // Load save file
  const handleFileUpload = useCallback(async (file: File) => {
    if (!file.name.endsWith('.sav')) {
      toast({ title: '错误', description: '请选择 .sav 格式的群星存档文件', variant: 'destructive' });
      return;
    }
    setLoading(true);
    try {
      const result = await uploadSave(file);
      setMeta(result.meta);
      setEditName(result.meta.name);
      setEditDate(result.meta.date);
      setSelectedCountry(result.player_country_id);
      setLoaded(true);
      setActiveTab('overview');
      toast({ title: '存档加载成功', description: `${result.meta.name} (${result.meta.date})` });

      // Load additional data
      const [statsData, countriesData, resourcesData, speciesData] = await Promise.all([
        getStats(),
        getCountries(),
        getResources(result.player_country_id),
        getSpecies(),
      ]);
      setStats(statsData);
      setCountries(countriesData.countries);
      setResources(resourcesData.resources);
      setResourceCategories(resourcesData.categories);
      setSpecies(speciesData.species);

      // Init edit resources
      const initEdit: Record<string, string> = {};
      for (const [k, v] of Object.entries(resourcesData.resources)) {
        initEdit[k] = v.value.toFixed(2);
      }
      setEditResources(initEdit);
    } catch (err) {
      toast({
        title: '加载失败',
        description: err instanceof Error ? err.message : '未知错误',
        variant: 'destructive',
      });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  // Handle drag & drop
  const [dragOver, setDragOver] = useState(false);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFileUpload(file);
  }, [handleFileUpload]);

  // Save resources
  const handleSaveResources = async () => {
    setSaving(true);
    try {
      const parsed: Record<string, number> = {};
      for (const [k, v] of Object.entries(editResources)) {
        const num = parseFloat(v);
        if (!isNaN(num)) parsed[k] = num;
      }
      await updateResources(selectedCountry, parsed);
      // Refresh resources
      const data = await getResources(selectedCountry);
      setResources(data.resources);
      const initEdit: Record<string, string> = {};
      for (const [k, v] of Object.entries(data.resources)) {
        initEdit[k] = v.value.toFixed(2);
      }
      setEditResources(initEdit);
      toast({ title: '保存成功', description: '资源已更新' });
    } catch (err) {
      toast({ title: '保存失败', description: err instanceof Error ? err.message : '未知错误', variant: 'destructive' });
    } finally {
      setSaving(false);
    }
  };

  // Save date
  const handleSaveDate = async () => {
    if (!/^\d{4}\.\d{2}\.\d{2}$/.test(editDate)) {
      toast({ title: '格式错误', description: '日期格式应为 YYYY.MM.DD', variant: 'destructive' });
      return;
    }
    setSaving(true);
    try {
      await updateDate(editDate);
      const newStats = await getStats();
      setStats(newStats);
      if (meta) setMeta({ ...meta, date: editDate });
      toast({ title: '日期已更新', description: editDate });
    } catch (err) {
      toast({ title: '更新失败', description: err instanceof Error ? err.message : '未知错误', variant: 'destructive' });
    } finally {
      setSaving(false);
    }
  };

  // Save name
  const handleSaveName = async () => {
    if (!editName.trim()) {
      toast({ title: '名称不能为空', variant: 'destructive' });
      return;
    }
    setSaving(true);
    try {
      await updateName(editName.trim());
      if (meta) setMeta({ ...meta, name: editName.trim() });
      const newCountries = await getCountries();
      setCountries(newCountries.countries);
      toast({ title: '名称已更新', description: editName.trim() });
    } catch (err) {
      toast({ title: '更新失败', description: err instanceof Error ? err.message : '未知错误', variant: 'destructive' });
    } finally {
      setSaving(false);
    }
  };

  // Export
  const handleExport = async () => {
    setExporting(true);
    try {
      const blob = await exportSave();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = meta ? `${meta.name.replace(/[^a-zA-Z0-9\u4e00-\u9fa5]/g, '_')}_modified.sav` : 'modified_save.sav';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast({ title: '导出成功', description: '修改后的存档已下载' });
    } catch (err) {
      toast({ title: '导出失败', description: err instanceof Error ? err.message : '未知错误', variant: 'destructive' });
    } finally {
      setExporting(false);
    }
  };

  // Reset
  const handleReset = async () => {
    setLoaded(false);
    setMeta(null);
    setStats(null);
    setResources({});
    setCountries([]);
    setSpecies([]);
    setEditResources({});
    try { await releaseSave(); } catch { /* ignore */ }
    toast({ title: '存档已释放' });
  };

  // Switch country
  const handleCountryChange = async (countryId: string) => {
    setSelectedCountry(countryId);
    try {
      const data = await getResources(countryId);
      setResources(data.resources);
      setResourceCategories(data.categories);
      const initEdit: Record<string, string> = {};
      for (const [k, v] of Object.entries(data.resources)) {
        initEdit[k] = v.value.toFixed(2);
      }
      setEditResources(initEdit);
    } catch (err) {
      toast({ title: '加载资源失败', description: err instanceof Error ? err.message : '', variant: 'destructive' });
    }
  };

  // Quick set resource value
  const setResourceValue = (key: string, value: string) => {
    setEditResources(prev => ({ ...prev, [key]: value }));
  };

  // ============ RENDER: UPLOAD SCREEN ============
  if (!loaded) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4"
        style={{ background: 'radial-gradient(ellipse at 20% 50%, rgba(30,10,60,0.8) 0%, rgba(5,5,15,1) 70%)' }}
      >
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          {/* Stars background */}
          {Array.from({ length: 80 }).map((_, i) => (
            <div
              key={i}
              className="absolute rounded-full bg-white"
              style={{
                width: Math.random() * 2 + 1,
                height: Math.random() * 2 + 1,
                top: `${Math.random() * 100}%`,
                left: `${Math.random() * 100}%`,
                opacity: Math.random() * 0.7 + 0.3,
                animation: `twinkle ${2 + Math.random() * 3}s ease-in-out ${Math.random() * 2}s infinite`,
              }}
            />
          ))}
        </div>

        <Card className="relative z-10 w-full max-w-lg border-amber-500/20 bg-black/60 backdrop-blur-xl"
          style={{ boxShadow: '0 0 80px rgba(245,158,11,0.1)' }}
        >
          <CardHeader className="text-center pb-2">
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-amber-500/10 border border-amber-500/30">
              <Star className="h-8 w-8 text-amber-400" />
            </div>
            <CardTitle className="text-2xl font-bold text-amber-100">
              群星存档修改器
            </CardTitle>
            <CardDescription className="text-amber-200/60 mt-1">
              Stellaris Save Editor  ·  支持 Caelum / 最新版本存档
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div
              className={`border-2 border-dashed rounded-xl p-10 text-center transition-all cursor-pointer ${
                dragOver
                  ? 'border-amber-400 bg-amber-500/10'
                  : 'border-gray-600 hover:border-amber-500/50 hover:bg-white/5'
              }`}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <input
                ref={fileInputRef}
                type="file" accept=".sav" className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleFileUpload(file);
                }}
              />
              {loading ? (
                <div className="flex flex-col items-center gap-3">
                  <Loader2 className="h-10 w-10 text-amber-400 animate-spin" />
                  <p className="text-amber-200">正在解析存档，请稍候...</p>
                  <p className="text-xs text-amber-200/40">大型存档可能需要10-20秒</p>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-3">
                  <Upload className="h-10 w-10 text-amber-400/60" />
                  <p className="text-amber-100 font-medium">拖拽 .sav 存档文件到此处</p>
                  <p className="text-sm text-amber-200/50">或点击选择文件</p>
                </div>
              )}
            </div>
            <div className="mt-4 flex items-center gap-2 text-xs text-amber-200/30 justify-center">
              <Shield className="h-3 w-3" />
              <span>所有解析均在本地完成，不会上传任何数据</span>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ============ RENDER: EDITOR SCREEN ============
  return (
    <div className="min-h-screen flex flex-col"
      style={{ background: 'linear-gradient(135deg, rgba(5,5,20,1) 0%, rgba(15,10,30,1) 50%, rgba(5,10,25,1) 100%)' }}
    >
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-amber-500/10 bg-black/70 backdrop-blur-xl">
        <div className="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-500/15">
              <Star className="h-4 w-4 text-amber-400" />
            </div>
            <div>
              <h1 className="text-sm font-bold text-amber-100 leading-tight">{meta?.name || '群星存档修改器'}</h1>
              <p className="text-xs text-amber-200/40">{meta?.version}  ·  {meta?.date}</p>
            </div>
            {meta?.ironman && (
              <Badge variant="outline" className="border-red-500/40 text-red-400 text-xs">
                铁人模式
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={handleReset}
              className="border-gray-600 text-gray-300 hover:text-white hover:bg-white/5">
              <RotateCcw className="h-3.5 w-3.5 mr-1" /> 释放存档
            </Button>
            <Button size="sm" onClick={handleExport} disabled={exporting}
              className="bg-amber-500 hover:bg-amber-400 text-black font-medium">
              {exporting ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Download className="h-3.5 w-3.5 mr-1" />}
              导出存档
            </Button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 max-w-7xl mx-auto w-full px-4 py-6">
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="bg-black/40 border border-amber-500/10 mb-6">
            <TabsTrigger value="overview" className="data-[state=active]:bg-amber-500/20 data-[state=active]:text-amber-100">
              <Globe className="h-3.5 w-3.5 mr-1.5" /> 总览
            </TabsTrigger>
            <TabsTrigger value="resources" className="data-[state=active]:bg-amber-500/20 data-[state=active]:text-amber-100">
              <Zap className="h-3.5 w-3.5 mr-1.5" /> 资源
            </TabsTrigger>
            <TabsTrigger value="countries" className="data-[state=active]:bg-amber-500/20 data-[state=active]:text-amber-100">
              <Flag className="h-3.5 w-3.5 mr-1.5" /> 国家
            </TabsTrigger>
            <TabsTrigger value="species" className="data-[state=active]:bg-amber-500/20 data-[state=active]:text-amber-100">
              <Dna className="h-3.5 w-3.5 mr-1.5" /> 物种
            </TabsTrigger>
          </TabsList>

          {/* ===== OVERVIEW TAB ===== */}
          <TabsContent value="overview" className="space-y-6">
            {/* Empire Info Card */}
            <Card className="border-amber-500/10 bg-black/40 backdrop-blur">
              <CardHeader className="pb-3">
                <CardTitle className="text-amber-100 text-base flex items-center gap-2">
                  <Star className="h-4 w-4" /> 帝国信息
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Name edit */}
                  <div className="space-y-2">
                    <Label className="text-amber-200/70 text-xs">帝国名称</Label>
                    <div className="flex gap-2">
                      <Input value={editName} onChange={e => setEditName(e.target.value)}
                        className="bg-white/5 border-gray-600 text-amber-50" />
                      <Button size="sm" onClick={handleSaveName} disabled={saving}
                        className="bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 border border-amber-500/30 shrink-0">
                        <Save className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                  {/* Date edit */}
                  <div className="space-y-2">
                    <Label className="text-amber-200/70 text-xs">游戏日期</Label>
                    <div className="flex gap-2">
                      <Input value={editDate} onChange={e => setEditDate(e.target.value)}
                        placeholder="YYYY.MM.DD" className="bg-white/5 border-gray-600 text-amber-50" />
                      <Button size="sm" onClick={handleSaveDate} disabled={saving}
                        className="bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 border border-amber-500/30 shrink-0">
                        <Save className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Stats Grid */}
            {stats && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {[
                  { label: '游戏日期', value: stats.date, icon: <Calendar className="h-4 w-4 text-blue-400" /> },
                  { label: '帝国规模', value: stats.empire_size, icon: <MapPin className="h-4 w-4 text-green-400" /> },
                  { label: '科技数量', value: stats.tech_count, icon: <BookOpen className="h-4 w-4 text-purple-400" /> },
                  { label: '舰队规模', value: stats.fleet_size, icon: <Rocket className="h-4 w-4 text-red-400" /> },
                  { label: '军事力量', value: Math.round(stats.military_power).toLocaleString(), icon: <Swords className="h-4 w-4 text-orange-400" /> },
                  { label: '国家数量', value: stats.num_countries, icon: <Flag className="h-4 w-4 text-cyan-400" /> },
                  { label: '物种数量', value: stats.num_species, icon: <Dna className="h-4 w-4 text-green-300" /> },
                  { label: '行星数量', value: stats.owned_planets_count, icon: <Globe className="h-4 w-4 text-amber-400" /> },
                ].map(stat => (
                  <Card key={stat.label} className="border-gray-700/50 bg-black/30">
                    <CardContent className="p-4 flex items-center gap-3">
                      <div className="p-2 rounded-lg bg-white/5">{stat.icon}</div>
                      <div>
                        <p className="text-xs text-gray-400">{stat.label}</p>
                        <p className="text-lg font-bold text-amber-100">{stat.value}</p>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}

            {/* DLCs */}
            {meta?.dlcs && meta.dlcs.length > 0 && (
              <Card className="border-gray-700/50 bg-black/30">
                <CardHeader className="pb-3">
                  <CardTitle className="text-amber-100 text-base flex items-center gap-2">
                    <FileText className="h-4 w-4" /> 已启用DLC ({meta.dlcs.length})
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-2">
                    {meta.dlcs.map((dlc, i) => (
                      <Badge key={i} variant="outline" className="border-gray-600 text-gray-300 text-xs">
                        {dlc.replace(/ Story Pack$| Species Pack$/i, '').replace(/^(The )/i, '')}
                      </Badge>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* ===== RESOURCES TAB ===== */}
          <TabsContent value="resources" className="space-y-6">
            {/* Country selector */}
            <Card className="border-amber-500/10 bg-black/40">
              <CardContent className="p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <Label className="text-amber-200/70 text-sm">选择国家:</Label>
                  <select
                    value={selectedCountry}
                    onChange={e => handleCountryChange(e.target.value)}
                    className="bg-white/5 border border-gray-600 text-amber-50 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:border-amber-500/50"
                  >
                    {countries.filter(c => c.name).map(c => (
                      <option key={c.id} value={c.id} className="bg-gray-900">
                        {c.name} (ID: {c.id})
                      </option>
                    ))}
                  </select>
                </div>
                <Button onClick={handleSaveResources} disabled={saving}
                  className="bg-amber-500 hover:bg-amber-400 text-black font-medium">
                  {saving ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <Save className="h-3.5 w-3.5 mr-1.5" />}
                  保存所有资源
                </Button>
              </CardContent>
            </Card>

            {/* Resource categories */}
            {Object.entries(resourceCategories).map(([category, keys]) => {
              const filteredKeys = keys.filter(k => resources[k]);
              if (filteredKeys.length === 0) return null;
              return (
                <Card key={category} className="border-gray-700/50 bg-black/30">
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-amber-100 text-sm flex items-center gap-2">
                        {category}
                      </CardTitle>
                      <Badge className={`text-xs border ${CATEGORY_COLORS[category] || ''}`}>
                        {filteredKeys.length} 项
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                      {filteredKeys.map(key => {
                        const res = resources[key];
                        if (!res) return null;
                        const hasChanged = editResources[key] &&
                          Math.abs(parseFloat(editResources[key]) - res.value) > 0.001;
                        return (
                          <div key={key} className={
                            hasChanged
                              ? 'flex items-center gap-3 p-3 rounded-lg border transition-colors bg-amber-500/10 border-amber-500/30'
                              : 'flex items-center gap-3 p-3 rounded-lg border transition-colors bg-white/[0.02] border-gray-700/30 hover:border-gray-600/50'
                          }>
                            <div className="shrink-0">
                              {RESOURCE_ICON_MAP[key] || <Zap className="h-4 w-4 text-gray-400" />}
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className="text-xs text-gray-400 truncate">{res.label}</p>
                              <Input
                                type="number"
                                step="0.01"
                                value={editResources[key] || ''}
                                onChange={e => setResourceValue(key, e.target.value)}
                                className="h-7 text-sm bg-transparent border-gray-600/50 text-amber-50 mt-0.5"
                              />
                            </div>
                            {hasChanged && (
                              <div className="text-right shrink-0">
                                <p className="text-[10px] text-gray-500">原值</p>
                                <p className="text-xs text-gray-400">{res.value.toFixed(1)}</p>
                              </div>
                            )}
                            {res.income > 0 && (
                              <div className="text-right shrink-0">
                                <p className="text-[10px] text-gray-500">月入</p>
                                <p className="text-xs text-green-400">+{res.income.toFixed(1)}</p>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </CardContent>
                </Card>
              );
            })}

            {/* Quick actions */}
            <Card className="border-amber-500/10 bg-black/40">
              <CardHeader className="pb-3">
                <CardTitle className="text-amber-100 text-sm">快速操作</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-2">
                  {[
                    { label: '全部设为 99999', multiplier: 99999 },
                    { label: '全部设为 50000', multiplier: 50000 },
                    { label: '全部设为 10000', multiplier: 10000 },
                    { label: '全部翻倍', multiplier: -2 },
                    { label: '全部清零', multiplier: 0 },
                  ].map(action => (
                    <Button key={action.label} variant="outline" size="sm"
                      className="border-gray-600 text-gray-300 hover:text-amber-200 hover:border-amber-500/30"
                      onClick={() => {
                        const newRes: Record<string, string> = {};
                        for (const k of Object.keys(editResources)) {
                          if (action.multiplier === -2) {
                            newRes[k] = (parseFloat(editResources[k] || '0') * 2).toFixed(2);
                          } else {
                            newRes[k] = action.multiplier.toFixed(2);
                          }
                        }
                        setEditResources(newRes);
                      }}
                    >
                      {action.label}
                    </Button>
                  ))}
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* ===== COUNTRIES TAB ===== */}
          <TabsContent value="countries">
            <Card className="border-gray-700/50 bg-black/30">
              <CardHeader className="pb-3">
                <CardTitle className="text-amber-100 text-base flex items-center gap-2">
                  <Flag className="h-4 w-4" /> 所有国家 ({countries.length})
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ScrollArea className="max-h-[600px]">
                  <div className="space-y-2">
                    {countries.filter(c => c.name).sort((a, b) => {
                      if (a.id === stats?.player_country_id) return -1;
                      if (b.id === stats?.player_country_id) return 1;
                      return 0;
                    }).map(country => (
                      <div key={country.id}
                        className={`flex items-center justify-between p-3 rounded-lg border transition-colors cursor-pointer
                          ${country.id === selectedCountry
                            ? 'bg-amber-500/10 border-amber-500/30'
                            : 'bg-white/[0.02] border-gray-700/30 hover:border-gray-600/50'
                          }
                        `}
                        onClick={() => {
                          handleCountryChange(country.id);
                          setActiveTab('resources');
                        }}
                      >
                        <div className="flex items-center gap-3">
                          {country.id === stats?.player_country_id && (
                            <Badge className="bg-amber-500/20 text-amber-300 border-amber-500/30 text-xs">
                              玩家
                            </Badge>
                          )}
                          <div>
                            <p className="text-sm text-amber-50 font-medium">{country.name}</p>
                            <p className="text-xs text-gray-500">ID: {country.id}  ·  {country.type}</p>
                          </div>
                        </div>
                        <div className="flex items-center gap-4 text-xs text-gray-400">
                          <span className="flex items-center gap-1">
                            <Swords className="h-3 w-3" /> {Math.round(country.military_power).toLocaleString()}
                          </span>
                          <span className="flex items-center gap-1">
                            <Rocket className="h-3 w-3" /> {country.fleet_size}
                          </span>
                          <ChevronRight className="h-4 w-4" />
                        </div>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>
          </TabsContent>

          {/* ===== SPECIES TAB ===== */}
          <TabsContent value="species">
            <Card className="border-gray-700/50 bg-black/30">
              <CardHeader className="pb-3">
                <CardTitle className="text-amber-100 text-base flex items-center gap-2">
                  <Dna className="h-4 w-4" /> 物种列表
                  {stats && <Badge className="bg-amber-500/20 text-amber-300 border-amber-500/30 text-xs">共 {stats.num_species} 个</Badge>}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ScrollArea className="max-h-[600px]">
                  <div className="space-y-2">
                    {species.filter(s => s.name && s.name !== '(未命名)').map(sp => (
                      <div key={sp.id} className="flex items-center justify-between p-3 rounded-lg border bg-white/[0.02] border-gray-700/30">
                        <div className="flex items-center gap-3">
                          <div className="h-8 w-8 rounded-full bg-gradient-to-br from-purple-500/30 to-cyan-500/30 border border-gray-600/50 flex items-center justify-center text-xs text-gray-400">
                            {sp.class}
                          </div>
                          <div>
                            <p className="text-sm text-amber-50 font-medium">{sp.name}</p>
                            <p className="text-xs text-gray-500">{sp.portrait}  ·  ID: {sp.id}</p>
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-1 max-w-xs justify-end">
                          {sp.traits.slice(0, 4).map((trait, i) => (
                            <Badge key={i} variant="outline" className="border-gray-600 text-gray-400 text-[10px]">
                              {trait.replace('trait_', '').replace(/_/g, ' ')}
                            </Badge>
                          ))}
                          {sp.traits.length > 4 && (
                            <Badge variant="outline" className="border-gray-600 text-gray-500 text-[10px]">
                              +{sp.traits.length - 4}
                            </Badge>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </main>

      {/* Footer */}
      <footer className="border-t border-gray-800/50 mt-auto">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between text-xs text-gray-500">
          <span>Stellaris Save Editor  ·  Paradox Clausewitz Engine</span>
          <span>支持版本: 3.x+ (含 Caelum)</span>
        </div>
      </footer>
    </div>
  );
}