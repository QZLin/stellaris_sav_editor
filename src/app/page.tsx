'use client';

import { useState, useRef } from 'react';
import { Upload, Download, Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useToast } from '@/hooks/use-toast';
import {
  uploadSave, getMeta, getStats, getResources,
  updateResources, updateDate, updateName,
  exportSave, releaseSave,
} from '@/lib/save-api';
import type { SaveMeta, GameStats, ResourceInfo, ResourcesResponse } from '@/lib/save-api';

type Screen = 'upload' | 'editor';

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
  const fileRef = useRef<HTMLInputElement>(null);
  const { toast } = useToast();

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    try {
      const res = await uploadSave(file);
      setFilename(res.filename);
      setMeta(res.meta);
      setEditName(res.meta.name);
      setSplitInfo(res.split_info ?? {});
      const [s, r] = await Promise.all([getStats(), getResources(res.player_country_id)]);
      setStats(s);
      setResources(r.resources);
      setResourceCategories(r.categories);
      setEditDate(s.date);
      const init: Record<string, string> = {};
      for (const [k, v] of Object.entries(r.resources)) init[k] = String(v.value);
      setEditResources(init);
      setScreen('editor');
      toast({ title: '上传成功', description: `${res.meta.name} (${res.meta.date})` });
    } catch (err: any) {
      toast({ title: '上传失败', description: err.message, variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  const handleSaveResources = async () => {
    if (!stats || !resources) return;
    const nums: Record<string, number> = {};
    for (const [k, v] of Object.entries(editResources)) {
      const n = Number(v);
      if (!isNaN(n)) nums[k] = n;
    }
    try {
      await updateResources(stats.player_country_id, nums);
      const r = await getResources(stats.player_country_id);
      setResources(r.resources);
      const init: Record<string, string> = {};
      for (const [k, v] of Object.entries(r.resources)) init[k] = String(v.value);
      setEditResources(init);
      toast({ title: '资源已保存' });
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
    setScreen('upload');
    setMeta(null);
    setStats(null);
    setResources(null);
    setEditResources({});
    setSplitInfo({});
    if (fileRef.current) fileRef.current.value = '';
  };

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
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">资源编辑</CardTitle>
                <Button size="sm" onClick={handleSaveResources}>保存全部</Button>
              </div>
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
