#!/usr/bin/env node
/**
 * 报价数据上传脚本
 * 用法: node upload-rates.js <data.json> [--uploader-id <id>] [--uploader-name <name>] [--mongo-uri <uri>] [--report-dir <dir>]
 *
 * data.json 格式:
 * {
 *   "project": { "country": "泰国", "city": "曼谷", "specialty": "数据中心", "projectName": "..." },
 *   "suppliers": [{
 *     "name": "Supplier Co., Ltd.",
 *     "name_cn": "供应商中文名",
 *     "contact": "...",
 *     "phone": "...",
 *     "address": "...",
 *     "address_cn": "...",
 *     "projectName": "...",
 *     "projectName_cn": "...",
 *     "sourceFile": "相对路径/文件名.pdf",
 *     "remarks": "...",
 *     "items": [{
 *       "name": "Material Name",
 *       "name_cn": "材料中文名",
 *       "features": "Spec...",
 *       "features_cn": "规格中文...",
 *       "unit": "m³",
 *       "price_excl_tax": "1234.56",
 *       "price_incl_tax": "1320.98",
 *       "date": "2026-03-16"
 *     }]
 *   }]
 * }
 */

const fs = require('fs');
const path = require('path');
const mongoose = require('mongoose');

// ========== 命令行参数解析 ==========
const args = process.argv.slice(2);
const dataFile = args.find(a => !a.startsWith('--') && a.endsWith('.json'));
if (!dataFile) {
  console.error('Usage: node upload-rates.js <data.json> [options]');
  console.error('Options: --uploader-id <id> --uploader-name <name> --mongo-uri <uri> --report-dir <dir>');
  process.exit(1);
}

function getArg(name, fallback) {
  const idx = args.indexOf(name);
  return idx >= 0 && idx + 1 < args.length ? args[idx + 1] : fallback;
}

const UPLOADER_ID = getArg('--uploader-id', '697ae529b6529f32ed704b5f');
const UPLOADER_NAME = getArg('--uploader-name', '系统管理员01');
const MONGODB_URI = getArg('--mongo-uri', 'mongodb://127.0.0.1:37117/cost_data_platform?directConnection=true');
const REPORT_DIR = getArg('--report-dir', path.dirname(path.resolve(dataFile)));

// ========== 读取数据 ==========
const data = JSON.parse(fs.readFileSync(dataFile, 'utf-8'));
const project = data.project || {};
const suppliers = data.suppliers || [];

// ========== 构建Rate记录 ==========
function buildRateRecords() {
  const records = [];
  for (const supplier of suppliers) {
    for (const item of supplier.items) {
      records.push({
        country: project.country || '泰国',
        country_en: project.country_en || 'Thailand',
        city: project.city || '',
        city_en: project.city_en || '',
        specialty: project.specialty || '',
        specialty_en: project.specialty_en || '',
        name: item.name,
        name_en: item.name_en || item.name,
        features: item.features || '',
        features_en: item.features_en || item.features || '',
        unit: item.unit,
        unit_en: item.unit_en || item.unit,
        price_excl_tax: String(item.price_excl_tax),
        price_incl_tax: String(item.price_incl_tax),
        currency: item.currency || 'THB',
        date: new Date(item.date),
        supplier: supplier.name,
        supplier_en: supplier.name_en || supplier.name,
        contact: supplier.contact || '',
        phone: supplier.phone || '',
        address: supplier.address || '',
        projectName: supplier.projectName || project.projectName || '',
        projectName_en: supplier.projectName_en || supplier.projectName || '',
        fileName: supplier.sourceFile || '',
        uploaderId: UPLOADER_ID,
        uploaderNickname: UPLOADER_NAME,
        status: 'approved',
        approvalTimestamp: new Date(),
        searchText: `${item.name} ${item.features} ${supplier.name} ${project.country} ${project.specialty}`,
        fieldsTranslated: true,
      });
    }
  }
  return records;
}

// ========== HTML报告生成 ==========
function generateHtmlReport(uploadedRecords, stats) {
  const templatePath = path.join(__dirname, '..', 'assets', 'report-template.html');
  let template;
  if (fs.existsSync(templatePath)) {
    template = fs.readFileSync(templatePath, 'utf-8');
  } else {
    template = fs.readFileSync(path.join(__dirname, '..', '..', 'assets', 'report-template.html'), 'utf-8');
  }

  // 生成表格行
  let tableRows = '';
  let rowNum = 1;
  for (const supplier of suppliers) {
    for (const item of supplier.items) {
      const tax = (parseFloat(item.price_excl_tax) * 0.07).toFixed(2);
      tableRows += `
        <tr>
          <td>${rowNum}</td>
          <td>${project.specialty || ''}</td>
          <td>${item.name_cn || item.name}</td>
          <td>${item.features_cn || item.features || ''}</td>
          <td>${item.unit}</td>
          <td class="num">${Number(item.price_excl_tax).toLocaleString('en-US', { minimumFractionDigits: 2 })}</td>
          <td class="num">${tax}</td>
          <td class="num">${Number(item.price_incl_tax).toLocaleString('en-US', { minimumFractionDigits: 2 })}</td>
          <td>${item.date}</td>
          <td>${item.currency || 'THB'}</td>
          <td>${supplier.name_cn || supplier.name}</td>
          <td>${supplier.contact || ''}</td>
          <td>${supplier.phone || ''}</td>
          <td>${supplier.address_cn || supplier.address || ''}</td>
          <td>${supplier.remarks || ''}</td>
        </tr>`;
      rowNum++;
    }
  }

  const totalRecords = uploadedRecords.length;
  const avgPrice = uploadedRecords.reduce((s, r) => s + parseFloat(r.price_excl_tax), 0) / totalRecords;

  // 替换模板占位符
  const html = template
    .replace('{{REPORT_TITLE}}', `${project.country || ''}${project.specialty || ''}报价数据上传报告`)
    .replace('{{GENERATED_TIME}}', new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }))
    .replace('{{SUPPLIER_COUNT}}', suppliers.length)
    .replace('{{TOTAL_RECORDS}}', totalRecords)
    .replace('{{AVG_PRICE}}', avgPrice.toFixed(2))
    .replace('{{CURRENCY}}', uploadedRecords[0]?.currency || 'THB')
    .replace('{{UNIT}}', uploadedRecords[0]?.unit || '')
    .replace('{{SUPPLIER_NAMES}}', suppliers.map(s => s.name_cn || s.name).join(', '))
    .replace('{{TABLE_ROWS}}', tableRows)
    .replace('{{SUPPLIER_DETAILS}}', suppliers.map((s, i) => `
        <div class="supplier-info">
          <strong>${i + 1}. ${s.name_cn || s.name} (${s.name})</strong><br>
          联系人: ${s.contact || '-'} | 电话: ${s.phone || '-'}<br>
          地址: ${s.address_cn || s.address || '-'}<br>
          项目: ${s.projectName_cn || s.projectName || '-'}<br>
          源文件: ${s.sourceFile || '-'}<br>
          备注: ${s.remarks || '-'}
        </div>`).join(''))
    .replace('{{CONVERSION_METHOD}}', data.conversionMethod || 'PDF→Markdown, 图片→OCR, Excel→document-ingest')
    .replace('{{TRANSLATION_NOTE}}', data.translationNote || '非英文内容已翻译为中文')
    .replace('{{PRICING_NOTE}}', data.pricingNote || 'VAT 7%计算')
    .replace('{{DB_NAME}}', 'cost_data_platform.rates')
    .replace('{{UPLOAD_STATUS}}', stats.status === 'success' ? '成功' : '失败: ' + (stats.error || ''))
    .replace('{{INSERTED_COUNT}}', stats.insertedCount || 0)
    .replace('{{DELETED_COUNT}}', stats.deletedCount || 0);

  return html;
}

// ========== 数据库操作 ==========
async function uploadToDb(records) {
  const Rate = mongoose.model('Rate', new mongoose.Schema({}, { strict: false, timestamps: true }), 'rates');

  // 删除相同国家和项目中的旧数据
  const deleteFilter = {
    country: project.country,
    projectName: { $in: [...new Set(suppliers.map(s => s.projectName))] },
    date: { $gte: new Date('2026-01-01') },
  };

  const existingCount = await Rate.countDocuments(deleteFilter);
  if (existingCount > 0) {
    console.log(`  Found ${existingCount} existing records, removing...`);
    await Rate.deleteMany(deleteFilter);
    console.log(`  Removed ${existingCount} old records.`);
  }

  const result = await Rate.insertMany(records);
  console.log(`  Inserted ${result.length} records.`);
  return { insertedCount: result.length, deletedCount: existingCount };
}

// ========== 主流程 ==========
async function main() {
  console.log('=== 报价数据上传 ===\n');
  console.log(`Data file: ${dataFile}`);
  console.log(`Suppliers: ${suppliers.length}`);
  console.log(`Total items: ${suppliers.reduce((s, sup) => s + sup.items.length, 0)}\n`);

  const records = buildRateRecords();

  // 1. 连接数据库
  console.log('Connecting to MongoDB...');
  await mongoose.connect(MONGODB_URI, { serverSelectionTimeoutMS: 10000 });
  console.log('Connected.\n');

  // 2. 上传
  console.log('Uploading...');
  let stats = { status: 'pending', insertedCount: 0, deletedCount: 0 };
  try {
    const result = await uploadToDb(records);
    stats.status = 'success';
    stats.insertedCount = result.insertedCount;
    stats.deletedCount = result.deletedCount;
  } catch (err) {
    stats.status = 'error';
    stats.error = err.message;
    console.error(`Upload failed: ${err.message}`);
  }

  // 3. 生成报告
  if (!fs.existsSync(REPORT_DIR)) fs.mkdirSync(REPORT_DIR, { recursive: true });
  const reportPath = path.join(REPORT_DIR, '报价数据上传报告.html');
  const html = generateHtmlReport(records, stats);
  fs.writeFileSync(reportPath, html, 'utf-8');
  console.log(`\nReport saved: ${reportPath}`);

  // 4. 保存中间JSON
  const outputPath = path.join(REPORT_DIR, '_converted', 'uploaded-data.json');
  if (!fs.existsSync(path.dirname(outputPath))) fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, JSON.stringify({ generatedAt: new Date().toISOString(), totalRecords: records.length, records }, null, 2), 'utf-8');
  console.log(`Data saved: ${outputPath}`);

  await mongoose.disconnect();
  console.log('\n=== Done ===');
}

main().catch(err => {
  console.error('Fatal:', err);
  process.exit(1);
});
