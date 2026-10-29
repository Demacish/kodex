package app.kodex.data.db

import android.content.Context
import androidx.room3.AutoMigration
import androidx.room3.Database
import androidx.room3.Room
import androidx.room3.RoomDatabase

/**
 * The device's copy of the catalog, its reading positions, its downloads and its bookmarks.
 * Every schema change is a migration (schemas/ holds the exported versions); 2 added columns
 * and the bookmarks.
 */
@Database(
    entities = [
        LibraryEntity::class, SeriesEntity::class, BookEntity::class, CollectionEntity::class,
        CollectionBookEntity::class, ProgressEntity::class, OutboxEntity::class, SyncStateEntity::class,
        DownloadEntity::class, BookmarkEntity::class,
    ],
    version = 2,
    exportSchema = true,
    autoMigrations = [AutoMigration(from = 1, to = 2)],
)
abstract class KodexDatabase : RoomDatabase() {
    abstract fun catalog(): CatalogDao

    abstract fun state(): StateDao

    abstract fun downloads(): DownloadDao

    abstract fun bookmarks(): BookmarkDao

    companion object {
        fun build(context: Context): KodexDatabase =
            Room.databaseBuilder(context.applicationContext, KodexDatabase::class.java, "kodex.db").build()

        fun inMemory(context: Context): KodexDatabase =
            Room.inMemoryDatabaseBuilder(context.applicationContext, KodexDatabase::class.java).build()
    }
}
